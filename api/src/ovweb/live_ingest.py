"""Live pipeline: supervisor broadcaster -> tshark -> reassembly -> SQLite + WebSocket fan-out.

One `LiveSession` per active capture. It:
  1. Subscribes to the in-process `Supervisor.broadcaster` to receive pcap bytes.
  2. Pipes those bytes through a named FIFO into `tshark -r <fifo> -T fields ...`.
  3. Parses tshark stdout line-by-line (same parser as decode-session),
     runs it through the incremental Reassembler FSM.
  4. Persists each Transfer into the session DB.
  5. Broadcasts each Transfer to WebSocket subscribers.

The FIFO + `tshark -r <fifo>` arrangement is unchanged from the split-container
phase because the asyncio subprocess-stdin quirk (`tshark -r -` rejects an
asyncio pipe with "standard input is a special file or socket") is still
present. Writes into the FIFO now come from an in-process asyncio queue
instead of a UNIX socket.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sqlite3
import tempfile
from collections.abc import AsyncIterator

from .capture.supervisor import Supervisor
from .ingest.filter import LiveFilter
from .ingest.reassembly import Reassembler, Transfer
from .ingest.tshark import TSHARK_FIELDS_ARGS, UsbLinkPacket, parse_fields_line

log = logging.getLogger(__name__)


# Default channels a new WebSocket subscriber is opted into. The raw firehose
# is opt-in: the UI subscribes to it only when the user expands the
# "Raw transfers" <details> pane.
DEFAULT_CHANNELS: frozenset[str] = frozenset({"summary", "events"})
ALL_CHANNELS:     frozenset[str] = frozenset({"summary", "events", "firehose"})


class Broadcaster:
    """WebSocket fan-out with per-subscriber channel masks. Messages tagged
    with a `channel` other than `None` reach only subscribers whose mask
    includes that channel. `channel=None` messages (e.g. 'end', 'error')
    reach every subscriber regardless of mask.

    Slow subscribers drop messages rather than stall capture.
    """

    MAX_QUEUE = 1024

    def __init__(self) -> None:
        # queue -> channel set (mutable; updated on client 'subscribe' RPC)
        self._subs: dict[asyncio.Queue, set[str]] = {}

    def subscribe(self, channels: set[str] | None = None) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(self.MAX_QUEUE)
        self._subs[q] = set(channels) if channels is not None else set(DEFAULT_CHANNELS)
        return q

    def set_channels(self, q: asyncio.Queue, channels: set[str]) -> None:
        if q in self._subs:
            # Only accept channels we actually publish into; silently drop any
            # junk the client sent so typos don't grant unintended access.
            self._subs[q] = {c for c in channels if c in ALL_CHANNELS}

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.pop(q, None)

    def publish(self, msg: dict, channel: str | None = None) -> None:
        for q, chans in list(self._subs.items()):
            if channel is not None and channel not in chans:
                continue
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                log.warning("ws subscriber slow, dropping message")


class LiveSession:
    """The active ingest task tied to one sessions-row id."""

    # Cadence of the supervisor-state poll that feeds `LiveFilter.note_supervisor_state`.
    # 200 ms is quick enough to catch speed-lock transitions without
    # inflating asyncio work at idle.
    SUPERVISOR_POLL_INTERVAL = 0.2

    def __init__(
        self,
        session_id: int,
        supervisor: Supervisor,
        db: sqlite3.Connection,
        broadcaster: Broadcaster,
    ) -> None:
        self.session_id = session_id
        self.supervisor = supervisor
        self.db = db
        self.broadcaster = broadcaster
        self._task: asyncio.Task | None = None
        self._summary_task: asyncio.Task | None = None
        self._state_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._packets_seen = 0
        self._transfers_seen = 0

        # Filter bound to this session's broadcaster. publish_* callbacks
        # tag each message with its channel so the Broadcaster can route
        # only to subscribers that asked for that channel.
        self.filter = LiveFilter(
            publish_summary=lambda updates: self.broadcaster.publish(
                {"type": "endpoint_update", "session_id": session_id, "updates": updates},
                channel="summary",
            ),
            publish_event=lambda ev: self.broadcaster.publish(
                {"type": "event", "session_id": session_id, **ev},
                channel="events",
            ),
            publish_raw=lambda msg: self.broadcaster.publish(
                {**msg, "session_id": session_id},
                channel="firehose",
            ),
        )

    @property
    def packets_seen(self) -> int:
        return self._packets_seen

    @property
    def transfers_seen(self) -> int:
        return self._transfers_seen

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("already running")
        self._task = asyncio.create_task(self._run(), name=f"live-ingest-{self.session_id}")
        self._summary_task = asyncio.create_task(
            self.filter.run_summary_ticker(), name=f"filter-ticker-{self.session_id}")
        self._state_task = asyncio.create_task(
            self._poll_supervisor_state(), name=f"filter-state-{self.session_id}")

    async def stop(self) -> None:
        self._stop_event.set()
        # Cancel ancillary tasks first; they hold no hard resources and exit
        # quickly, letting the main ingest cleanup sequence be uncontested.
        for t in (self._summary_task, self._state_task):
            if t is not None:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
        self._summary_task = None
        self._state_task = None
        if self._task is not None:
            # The task is typically blocked inside tshark.stdout.readline();
            # cancellation is what actually unblocks it. The try/finally in
            # _packet_stream cleans up fifo + tshark + broadcaster subscription.
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _poll_supervisor_state(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.SUPERVISOR_POLL_INTERVAL)
                self.filter.note_supervisor_state(self.supervisor.status_dict())
        except asyncio.CancelledError:
            raise

    async def _run(self) -> None:
        fsm = Reassembler()
        try:
            async for pkt in self._packet_stream():
                self._packets_seen += 1
                for xfer in fsm.feed(pkt):
                    self._emit(xfer)
            # Drain pending in-flight transactions on clean end-of-stream.
            for xfer in fsm.flush():
                self._emit(xfer)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("live ingest crashed: %s", e)
            self.broadcaster.publish({"type": "error", "error": str(e)})
        finally:
            self.broadcaster.publish({"type": "end", "session_id": self.session_id,
                                      "packets": self._packets_seen,
                                      "transfers": self._transfers_seen})

    def _emit(self, t: Transfer) -> None:
        # Persist every transfer — the UI filter is downstream of this and
        # only affects what's fanned out over the WebSocket.
        length = len(t.data_bytes) + (8 if t.setup_bytes else 0)
        self.db.execute(
            "INSERT INTO transfers "
            "(session_id, ts_ns, ep_addr, device_addr, direction, type, "
            "setup_bytes, data_bytes, length, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (self.session_id, t.ts_ns, t.endpoint, t.device_addr,
             t.direction, t.type,
             t.setup_bytes or None, t.data_bytes or None,
             length, t.status),
        )
        self._transfers_seen += 1
        # The filter publishes into the three broadcaster channels
        # (summary/events/firehose) as appropriate.
        self.filter.on_transfer(t)

    async def _packet_stream(self) -> AsyncIterator[UsbLinkPacket]:
        # 1. Subscribe to the supervisor's in-process pcap broadcaster.
        #    The queue yields the pcap global header (first) plus one pcap
        #    record per packet. Both are bytes; no socket reads.
        pcap_b = self.supervisor.broadcaster
        if pcap_b is None:
            raise RuntimeError("supervisor not open")
        pcap_queue = pcap_b.register()
        log.debug("pcap broadcaster subscribed for session %d", self.session_id)

        # 2. Create a FIFO for tshark input. `tshark -r -` fails under asyncio
        # subprocess pipes with "stdin is a special file or socket"; `-i -`
        # triggers dumpcap (needs wireshark group). A named pipe sidesteps
        # both paths and is explicitly supported by `tshark -r <fifo>`.
        fifo_dir = tempfile.mkdtemp(prefix="ov-live-")
        fifo_path = os.path.join(fifo_dir, "pcap.fifo")
        os.mkfifo(fifo_path)

        tshark = await asyncio.create_subprocess_exec(
            "tshark", "-r", fifo_path, *TSHARK_FIELDS_ARGS,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        log.info("live ingest: session=%d tshark pid=%d fifo=%s",
                 self.session_id, tshark.pid, fifo_path)

        # Open FIFO writer. Must happen AFTER tshark has the reader end,
        # otherwise open() blocks forever. tshark opens it on startup — we
        # briefly give it a moment to do so, then try; if the write-open
        # races ahead, the FIFO semantics still sort it out (reader side
        # will come along).
        fifo_fd = await asyncio.to_thread(os.open, fifo_path, os.O_WRONLY)
        fifo_writer = os.fdopen(fifo_fd, "wb", buffering=0)
        assert tshark.stdout is not None

        async def pump_in() -> None:
            total = 0
            try:
                while True:
                    # Drain the in-process queue into the FIFO. No EOF signal
                    # from the supervisor side — the task is cancelled
                    # externally when LiveSession.stop() fires (via the
                    # finally block below).
                    chunk = await pcap_queue.get()
                    total += len(chunk)
                    # os.write blocks; offload to thread so the event loop
                    # stays responsive. FIFOs are fast, so this is cheap.
                    await asyncio.to_thread(fifo_writer.write, chunk)
            finally:
                log.debug("pump_in exiting session=%d bytes=%d",
                          self.session_id, total)
                with contextlib.suppress(Exception):
                    fifo_writer.close()

        pump = asyncio.create_task(pump_in(), name="pcap-pump")
        n_lines = 0
        try:
            while True:
                line = await tshark.stdout.readline()
                if not line:
                    # Grab stderr for diagnosis; tshark closing stdout without
                    # output usually means it choked on the stdin format.
                    err = b""
                    with contextlib.suppress(Exception):
                        err = await asyncio.wait_for(tshark.stderr.read(8192), 1.0)
                    log.info("tshark EOF session=%d lines=%d stderr=%r",
                             self.session_id, n_lines, err[:400])
                    break
                n_lines += 1
                pkt = parse_fields_line(line.decode(errors="replace"))
                if pkt is None or pkt.is_sof:
                    continue
                yield pkt
                if self._stop_event.is_set():
                    break
        finally:
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump
            pcap_b.unregister(pcap_queue)
            with contextlib.suppress(ProcessLookupError):
                tshark.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(tshark.wait(), timeout=2.0)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(fifo_path)
            with contextlib.suppress(OSError):
                os.rmdir(fifo_dir)
