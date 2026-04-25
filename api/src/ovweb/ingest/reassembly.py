"""Group link-layer packets into transfer-level rows.

Minimum viable FSM for Phase 3:
  TOKEN + DATA + HANDSHAKE  -> one transfer
  TOKEN + HANDSHAKE         -> one transfer (NAK/STALL, no data)
  SETUP + DATA + HANDSHAKE  -> setup stage of a control transfer
                               (control data/status stages aggregated separately)

State is keyed by (device_addr, endpoint). Handshake / data packets don't
carry those fields on the wire, so we parse them from tshark's `usbll.src` /
`usbll.dst` strings of the form "<addr>.<ep>" or "host".

Isoch (no handshake), HS PING/NYET, and split-transaction SPLIT/PRE flows are
not yet handled; left for a later pass if the captures demand it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from .tshark import (
    DATA_PIDS,
    HANDSHAKE_PIDS,
    PID_ACK,
    PID_IN,
    PID_NAK,
    PID_NYET,
    PID_OUT,
    PID_PING,
    PID_SETUP,
    PID_SOF,
    PID_STALL,
    TOKEN_PIDS,
    UsbLinkPacket,
)

_HANDSHAKE_NAMES = {
    PID_ACK: "ack", PID_NAK: "nak", PID_STALL: "stall", PID_NYET: "nyet",
}


@dataclass(slots=True)
class Transfer:
    """One logical transfer on a given endpoint, with its data + outcome."""

    ts_ns: int
    device_addr: int
    endpoint: int
    direction: str          # 'in' | 'out' | 'setup'
    type: str               # 'control' | 'bulk_or_interrupt' | 'isoch' | 'unknown'
    setup_bytes: bytes      # 8 bytes for SETUP-origin transfers, b"" otherwise
    data_bytes: bytes       # DATA payload (empty if handshake-only)
    status: str             # 'ack' | 'nak' | 'stall' | 'nyet' | 'incomplete'


@dataclass(slots=True)
class _Pending:
    token: UsbLinkPacket
    data: UsbLinkPacket | None = None
    # Endpoint parsed once at token time so handshake lookup doesn't repeat the work.
    device_addr: int = 0
    endpoint: int = 0


class Reassembler:
    """Incremental FSM: feed one link-layer packet, get 0+ completed Transfers.

    State is keyed by (device_addr, endpoint). Use `feed()` per packet and
    `flush()` at end-of-stream to drain leftover in-flight transactions as
    `status='incomplete'`."""

    def __init__(self) -> None:
        self._pending: dict[tuple[int, int], _Pending] = {}

    def feed(self, p: UsbLinkPacket) -> list[Transfer]:
        if p.pid == PID_SOF:
            return []

        if p.pid in TOKEN_PIDS:
            if p.device_addr is None or p.endpoint is None:
                return []
            key = (p.device_addr, p.endpoint)
            # New token before the prior transfer completed = incomplete prior.
            out: list[Transfer] = []
            if key in self._pending:
                out.append(_materialise(self._pending.pop(key), status="incomplete"))
            self._pending[key] = _Pending(
                token=p, device_addr=p.device_addr, endpoint=p.endpoint,
            )
            return out

        if p.pid in DATA_PIDS:
            key = _endpoint_from_data(p)
            if key is None:
                return []
            st = self._pending.get(key)
            if st is None:
                # Orphan DATA; OV3 likely missed the preceding token.
                return []
            st.data = p
            return []

        if p.pid in HANDSHAKE_PIDS:
            key = _endpoint_from_handshake(p)
            if key is None:
                return []
            st = self._pending.pop(key, None)
            if st is None:
                return []
            return [_materialise(st, status=_HANDSHAKE_NAMES[p.pid])]

        # PRE/ERR, SPLIT, RESERVED, unknown: skip for now.
        return []

    def flush(self) -> list[Transfer]:
        out = [_materialise(st, status="incomplete") for st in self._pending.values()]
        self._pending.clear()
        return out


def reassemble(packets: Iterator[UsbLinkPacket]) -> Iterator[Transfer]:
    """Thin generator wrapper around Reassembler for the batch (decode-session)
    path. Live ingest uses the class directly."""
    fsm = Reassembler()
    for p in packets:
        yield from fsm.feed(p)
    yield from fsm.flush()


def _materialise(st: _Pending, *, status: str) -> Transfer:
    tok = st.token
    if tok.pid == PID_SETUP:
        direction = "setup"
        xtype = "control"
        setup_bytes = st.data.data if st.data else b""
        data_bytes = b""
    elif tok.pid == PID_IN:
        direction = "in"
        xtype = "bulk_or_interrupt"
        setup_bytes = b""
        data_bytes = st.data.data if st.data else b""
    elif tok.pid == PID_OUT:
        direction = "out"
        xtype = "bulk_or_interrupt"
        setup_bytes = b""
        data_bytes = st.data.data if st.data else b""
    elif tok.pid == PID_PING:
        # HS PING/NYET flow. Treat like an OUT probe; payload is always empty.
        direction = "out"
        xtype = "bulk_or_interrupt"
        setup_bytes = b""
        data_bytes = b""
    else:
        direction = "unknown"
        xtype = "unknown"
        setup_bytes = b""
        data_bytes = st.data.data if st.data else b""

    return Transfer(
        ts_ns=tok.ts_ns,
        device_addr=st.device_addr,
        endpoint=st.endpoint,
        direction=direction,
        type=xtype,
        setup_bytes=setup_bytes,
        data_bytes=data_bytes,
        status=status,
    )


def _endpoint_from_data(p: UsbLinkPacket) -> tuple[int, int] | None:
    """DATA packets don't carry address/endpoint on the wire; look at src/dst.
    One side is 'host', the other is '<addr>.<ep>' — return the latter."""
    peer = p.src if p.src != "host" else p.dst
    return _parse_addr_ep(peer)


def _endpoint_from_handshake(p: UsbLinkPacket) -> tuple[int, int] | None:
    peer = p.src if p.src != "host" else p.dst
    return _parse_addr_ep(peer)


def _parse_addr_ep(s: str) -> tuple[int, int] | None:
    if not s or s == "host":
        return None
    a, _, e = s.partition(".")
    try:
        return int(a), int(e)
    except ValueError:
        return None
