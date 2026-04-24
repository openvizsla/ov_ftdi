"""pcap -> stream of USB link-layer packets, via tshark.

`-T fields` is used instead of `-T json` for the link-layer pass: USBLL has a
flat schema, tab-separated fields stream at line granularity (no JSON parser
needed), and memory stays bounded regardless of capture size. Class-aware
decoders (HID / UVC / MSC) in a later phase will need `-T json` + ijson for
the nested protocol tree; that's a separate pass.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass

# USB PID bytes (complemented form, as captured on the wire).
# Source: USB 2.0 spec, Table 8-1.
PID_SOF           = 0xA5
PID_IN            = 0x69
PID_OUT           = 0xE1
PID_SETUP         = 0x2D
PID_DATA0         = 0xC3
PID_DATA1         = 0x4B
PID_DATA2         = 0x87
PID_MDATA         = 0x0F
PID_ACK           = 0xD2
PID_NAK           = 0x5A
PID_STALL         = 0x1E
PID_NYET          = 0x96
PID_PING          = 0xB4
PID_PRE_ERR       = 0x3C
PID_SPLIT         = 0x78
PID_RESERVED      = 0xF0

PID_NAMES: dict[int, str] = {
    PID_SOF: "SOF", PID_IN: "IN", PID_OUT: "OUT", PID_SETUP: "SETUP",
    PID_DATA0: "DATA0", PID_DATA1: "DATA1", PID_DATA2: "DATA2", PID_MDATA: "MDATA",
    PID_ACK: "ACK", PID_NAK: "NAK", PID_STALL: "STALL", PID_NYET: "NYET",
    PID_PING: "PING", PID_PRE_ERR: "PRE/ERR", PID_SPLIT: "SPLIT",
    PID_RESERVED: "RESERVED",
}

TOKEN_PIDS = {PID_IN, PID_OUT, PID_SETUP, PID_SOF, PID_PING}
DATA_PIDS = {PID_DATA0, PID_DATA1, PID_DATA2, PID_MDATA}
HANDSHAKE_PIDS = {PID_ACK, PID_NAK, PID_STALL, PID_NYET}


@dataclass(slots=True)
class UsbLinkPacket:
    """One link-layer packet from the OV3 capture, as dissected by tshark."""

    frame_num: int
    ts_ns: int
    pid: int
    device_addr: int | None   # tokens carry this; data / handshake do not
    endpoint: int | None
    src: str                  # "host" or "<dev>.<ep>"
    dst: str                  # same encoding
    data: bytes               # DATA payload (0 bytes for tokens/handshake)

    @property
    def pid_name(self) -> str:
        return PID_NAMES.get(self.pid, f"UNK({self.pid:#04x})")

    @property
    def is_sof(self) -> bool:
        return self.pid == PID_SOF


# The `-T fields` schema shared by offline (stream_packets) and live ingest.
# Consumers: see parse_fields_line() / stream_packets() / live_ingest.
FIELDS: tuple[str, ...] = (
    "frame.number",
    "frame.time_epoch",
    "usbll.pid",
    "usbll.device_addr",
    "usbll.endp",
    "usbll.src",
    "usbll.dst",
    "usbll.data",
)

TSHARK_FIELDS_ARGS: tuple[str, ...] = (
    "-T", "fields",
    "-E", "separator=\t",
    "-E", "occurrence=f",
    "-l",  # line-buffered stdout so live ingest doesn't wait for block fills
    *sum((("-e", f) for f in FIELDS), ()),
)

# Backwards-compat alias; remove once no references remain.
_FIELDS = FIELDS


def stream_packets(
    pcap_path: str,
    *,
    include_sofs: bool = False,
    tshark_bin: str = "tshark",
) -> Iterator[UsbLinkPacket]:
    """Spawn tshark on `pcap_path` and yield one UsbLinkPacket per frame.

    SOFs are dropped unless `include_sofs=True`. They account for ~99% of HS
    traffic and are useless for protocol analysis (see CLAUDE.md).
    """
    args = [tshark_bin, "-r", pcap_path, *TSHARK_FIELDS_ARGS]

    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    assert proc.stdout is not None
    unwinding = False
    try:
        for line in proc.stdout:
            pkt = parse_fields_line(line)
            if pkt is None:
                continue
            if pkt.is_sof and not include_sofs:
                continue
            yield pkt
    except BaseException:
        unwinding = True
        raise
    finally:
        proc.stdout.close()
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        rc = proc.wait()
        # Only surface a tshark error if we aren't already propagating one;
        # otherwise the non-zero rc usually just means SIGPIPE after our
        # consumer exited early.
        if rc != 0 and not unwinding:
            err = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"tshark exited {rc}: {err.strip()}")


def parse_fields_line(line: str) -> UsbLinkPacket | None:
    line = line.rstrip("\n")
    if not line:
        return None
    parts = line.split("\t")
    # Pad missing trailing fields (tshark drops them for some packets).
    while len(parts) < len(_FIELDS):
        parts.append("")

    try:
        frame_num = int(parts[0])
    except ValueError:
        return None

    ts_ns = _parse_epoch_ns(parts[1])
    pid = _parse_int_hex(parts[2])
    if pid is None:
        return None
    device_addr = _parse_int(parts[3])
    endpoint = _parse_int(parts[4])
    src = parts[5]
    dst = parts[6]
    data = _parse_hex_colons(parts[7])
    return UsbLinkPacket(
        frame_num=frame_num, ts_ns=ts_ns, pid=pid,
        device_addr=device_addr, endpoint=endpoint,
        src=src, dst=dst, data=data,
    )


def _parse_epoch_ns(s: str) -> int:
    # tshark prints "1777040336.931966287" — sec.nanosec, 9 fractional digits.
    if not s:
        return 0
    sec_str, _, frac_str = s.partition(".")
    sec = int(sec_str) if sec_str else 0
    # Pad/truncate fractional part to exactly 9 digits.
    frac_str = (frac_str + "0" * 9)[:9]
    return sec * 1_000_000_000 + int(frac_str)


def _parse_int(s: str) -> int | None:
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _parse_int_hex(s: str) -> int | None:
    if not s:
        return None
    try:
        return int(s, 16)
    except ValueError:
        return None


def _parse_hex_colons(s: str) -> bytes:
    # Accept either "00:00:0a:…" (tshark -T json) or "00000a…" (tshark -T
    # fields). Strip any separators and hex-decode.
    if not s:
        return b""
    stripped = s.replace(":", "").replace(" ", "")
    if len(stripped) % 2:
        # Malformed; safer to drop than raise from the hot path.
        return b""
    try:
        return bytes.fromhex(stripped)
    except ValueError:
        return b""
