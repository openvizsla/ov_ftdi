"""Live filtering FSM sitting between the reassembler and the WebSocket.

At HS the raw transfer stream is dominated by NAK poll chatter. This module
keeps the **full** trace going to SQLite (nothing is suppressed on the
persistence path) while feeding the UI two distilled streams:

- **endpoint_update** batches (every `summary_interval_ms`): one row per
  `(device_addr, ep_addr)` with cumulative counts, bytes, status mix, and the
  most recent payload. Updated in place client-side.
- **event** messages: surfaced only when something interesting happens —
  a new endpoint appears, a control transfer completes, an interrupt-IN
  payload changes byte-for-byte, a run of NAKs breaks, a STALL arrives,
  the supervisor's speed lock flips, the capture overflows.

The WebSocket handler multiplexes these over one connection via channel
subscriptions ("summary", "events", "firehose"); see `live_ingest.Broadcaster`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

from .reassembly import Transfer

log = logging.getLogger(__name__)


@dataclass(slots=True)
class EndpointStat:
    key: str                    # f"{device_addr}.{ep_addr}"
    device_addr: int
    ep_addr: int
    direction: str              # last-seen: 'in'|'out'|'setup'
    type: str                   # 'control' | 'bulk_or_interrupt' | 'isoch' | 'unknown'
    count: int
    bytes: int
    acks: int
    naks: int
    stalls: int
    nyets: int
    incompletes: int
    last_ts_ns: int
    last_data_hex: str | None
    status_run_kind: str        # status of current run-length
    status_run_len: int

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "device_addr": self.device_addr,
            "ep_addr": self.ep_addr,
            "direction": self.direction,
            "type": self.type,
            "count": self.count,
            "bytes": self.bytes,
            "acks": self.acks,
            "naks": self.naks,
            "stalls": self.stalls,
            "nyets": self.nyets,
            "incompletes": self.incompletes,
            "last_ts_ns": self.last_ts_ns,
            "last_data_hex": self.last_data_hex,
            "status_run_kind": self.status_run_kind,
            "status_run_len": self.status_run_len,
        }


# Run length at which an ack<->nak flip is considered "meaningful" enough
# to emit a status_flip event. Shorter flips are assumed to be bus jitter.
_FLIP_MIN_RUN = 3

# Statuses considered errors — any transition involving one of these always
# emits a status_flip event regardless of run length.
_ERROR_STATUSES = frozenset({"stall", "nyet", "incomplete"})


class LiveFilter:
    """Per-session filter. One instance is constructed when a LiveSession
    starts and discarded when it ends.

    All methods except `run_summary_ticker` run synchronously on the asyncio
    loop thread (called from `LiveSession._emit` which runs there).
    """

    def __init__(
        self,
        publish_summary: Callable[[list[dict]], None],
        publish_event: Callable[[dict], None],
        publish_raw: Callable[[dict], None],
        summary_interval_ms: int = 250,
    ) -> None:
        self._publish_summary = publish_summary
        self._publish_event = publish_event
        self._publish_raw = publish_raw
        self._interval = summary_interval_ms / 1000.0

        self._endpoints: dict[str, EndpointStat] = {}
        self._dirty: set[str] = set()
        self._last_in_payload: dict[str, bytes] = {}

        # Seed with an idle baseline so the first poll's "locked" status
        # actually fires a speed_locked event. `LiveSession.start()` runs the
        # supervisor start *before* spawning the poller, so by the time the
        # first poll tick happens the supervisor is already locked — we'd
        # miss the transition if we just cached the first observation.
        self._last_sv_status: dict = {"status": "idle", "overflows": 0}

    def on_transfer(self, t: Transfer) -> None:
        # 1. Firehose — every transfer, opt-in on the subscriber side.
        length = len(t.data_bytes) + (8 if t.setup_bytes else 0)
        self._publish_raw({
            "type": "transfer",
            "transfer": {
                "ts_ns": t.ts_ns,
                "device_addr": t.device_addr,
                "ep_addr": t.endpoint,
                "direction": t.direction,
                "type": t.type,
                "status": t.status,
                "length": length,
                "setup_hex": t.setup_bytes.hex() if t.setup_bytes else None,
                "data_hex": t.data_bytes.hex() if t.data_bytes else None,
            },
        })

        # 2. Endpoint stat update.
        key = f"{t.device_addr}.{t.endpoint}"
        ep = self._endpoints.get(key)
        if ep is None:
            ep = EndpointStat(
                key=key, device_addr=t.device_addr, ep_addr=t.endpoint,
                direction=t.direction, type=t.type,
                count=0, bytes=0,
                acks=0, naks=0, stalls=0, nyets=0, incompletes=0,
                last_ts_ns=0, last_data_hex=None,
                status_run_kind="", status_run_len=0,
            )
            self._endpoints[key] = ep
            self._publish_event({
                "kind": "new_endpoint",
                "ts_ns": t.ts_ns,
                "key": key,
                "device_addr": t.device_addr,
                "ep_addr": t.endpoint,
                "type": t.type,
                "direction": t.direction,
            })

        ep.direction = t.direction
        ep.type = t.type
        ep.count += 1
        ep.bytes += length
        ep.last_ts_ns = t.ts_ns
        ep.last_data_hex = t.data_bytes.hex() if t.data_bytes else None

        if t.status == "ack":
            ep.acks += 1
        elif t.status == "nak":
            ep.naks += 1
        elif t.status == "stall":
            ep.stalls += 1
        elif t.status == "nyet":
            ep.nyets += 1
        elif t.status == "incomplete":
            ep.incompletes += 1

        # 3. Status-flip detection on a run-length encoder.
        prev_kind = ep.status_run_kind
        prev_len = ep.status_run_len
        if t.status == prev_kind:
            ep.status_run_len = prev_len + 1
        else:
            if prev_kind and (
                t.status in _ERROR_STATUSES
                or prev_kind in _ERROR_STATUSES
                or prev_len >= _FLIP_MIN_RUN
            ):
                self._publish_event({
                    "kind": "status_flip",
                    "ts_ns": t.ts_ns,
                    "key": key,
                    "from": prev_kind,
                    "to": t.status,
                    "prev_run_len": prev_len,
                })
            ep.status_run_kind = t.status
            ep.status_run_len = 1

        # 4. Control transfer surface.
        if t.type == "control" and t.setup_bytes:
            self._publish_event({
                "kind": "control_transfer",
                "ts_ns": t.ts_ns,
                "key": key,
                "direction": t.direction,
                "status": t.status,
                "setup_hex": t.setup_bytes.hex(),
                "data_hex": t.data_bytes.hex() if t.data_bytes else None,
            })

        # 5. Payload-change detection on IN-ACK transfers.
        if (t.direction == "in" and t.status == "ack" and t.data_bytes):
            prev = self._last_in_payload.get(key)
            if prev != t.data_bytes:
                self._publish_event({
                    "kind": "payload_change",
                    "ts_ns": t.ts_ns,
                    "key": key,
                    "data_hex": t.data_bytes.hex(),
                    "first_seen": prev is None,
                })
                self._last_in_payload[key] = t.data_bytes

        self._dirty.add(key)

    def note_supervisor_state(self, status: dict) -> None:
        """Polled from an asyncio task; emits speed_locked/lost and overflow
        events on state deltas against the cached baseline."""
        prev = self._last_sv_status
        self._last_sv_status = status

        if prev.get("status") != status.get("status"):
            if status.get("status") == "locked":
                self._publish_event({
                    "kind": "speed_locked",
                    "speed": status.get("locked_speed"),
                })
            elif prev.get("status") == "locked":
                self._publish_event({"kind": "speed_lost"})

        prev_of = int(prev.get("overflows", 0))
        now_of = int(status.get("overflows", 0))
        if now_of > prev_of:
            self._publish_event({
                "kind": "overflow",
                "count": now_of,
                "delta": now_of - prev_of,
            })

    async def run_summary_ticker(self) -> None:
        """Run as a background task. Flushes changed endpoint rows to the
        summary channel every `summary_interval_ms`."""
        try:
            while True:
                await asyncio.sleep(self._interval)
                if not self._dirty:
                    continue
                updates = [self._endpoints[k].to_dict() for k in self._dirty]
                self._dirty.clear()
                self._publish_summary(updates)
        except asyncio.CancelledError:
            # Last flush on shutdown so the client sees the final counts.
            if self._dirty:
                updates = [self._endpoints[k].to_dict() for k in self._dirty]
                self._dirty.clear()
                with contextlib.suppress(Exception):
                    self._publish_summary(updates)
            raise

    def snapshot(self) -> list[dict]:
        """Full endpoint table for a new WebSocket subscriber."""
        return [ep.to_dict() for ep in self._endpoints.values()]
