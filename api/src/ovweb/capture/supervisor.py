"""In-process libopenvizsla supervisor. One instance per ov-api process.

Owns the FT2232H via libopenvizsla (C, via ctypes). The capture loop runs on
a pthread inside libopenvizsla; the packet callback fires on that thread and
marshals each pcap record to the asyncio loop via `loop.call_soon_threadsafe`.

The former two-UNIX-socket IPC surface (control.sock + pcap.sock) is gone —
FastAPI's lifespan manager constructs a single `Supervisor` instance and
consumers (`CaptureClient` for RPC, `LiveSession` for the pcap byte stream)
call it directly.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import struct
import threading
import time
from ctypes import (
    CDLL, CFUNCTYPE, POINTER, Structure,
    c_char_p, c_int, c_uint8, c_uint16, c_uint64, c_void_p,
)
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("ovweb.capture")


# ---- libopenvizsla ctypes bindings --------------------------------------

# enum ov_usb_speed (openvizsla.h)
OV_LOW_SPEED  = 0x4a
OV_FULL_SPEED = 0x49
OV_HIGH_SPEED = 0x48

SPEED_BY_NAME = {"ls": OV_LOW_SPEED, "fs": OV_FULL_SPEED, "hs": OV_HIGH_SPEED}

# ov_packet flag bits (byte 1 of the header)
OV_FLAGS_HF0_ERR   = 0x01
OV_FLAGS_HF0_OVF   = 0x02
OV_FLAGS_HF0_TRUNC = 0x08

OV_MAX_PACKET_SIZE = 1027
OV_TIMESTAMP_FREQ_HZ = 60_000_000


class ov_packet(Structure):
    """Matches `struct __attribute__((packed)) ov_packet` minus the FAM tail.
    The flexible `data[]` sits immediately after these 12 bytes."""
    _pack_ = 1
    _fields_ = [
        ("magic",     c_uint8),
        ("flags",     c_uint8),
        ("size",      c_uint16),
        ("timestamp", c_uint64),
    ]


OV_PACKET_HEADER_SIZE = ctypes.sizeof(ov_packet)  # = 12
PACKET_CB = CFUNCTYPE(None, POINTER(ov_packet), c_void_p)


def _load_libopenvizsla() -> CDLL:
    # Prefer the unversioned symlink; fall back to the current major (3) and
    # earlier majors so a bump doesn't break us.
    for soname in ("libopenvizsla.so", "libopenvizsla.so.3",
                   "libopenvizsla.so.2", "libopenvizsla.so.1",
                   "libopenvizsla.so.0"):
        try:
            lib = CDLL(soname)
            break
        except OSError:
            continue
    else:
        raise RuntimeError("libopenvizsla shared library not found on LD path")

    lib.ov_new.argtypes = [c_char_p]
    lib.ov_new.restype  = c_void_p
    lib.ov_open.argtypes = [c_void_p]
    lib.ov_open.restype  = c_int
    lib.ov_free.argtypes = [c_void_p]
    lib.ov_free.restype  = None
    lib.ov_set_usb_speed.argtypes = [c_void_p, c_int]
    lib.ov_set_usb_speed.restype  = c_int
    lib.ov_get_usb_speed.argtypes = [c_void_p, POINTER(c_int)]
    lib.ov_get_usb_speed.restype  = c_int
    lib.ov_capture_start.argtypes = [c_void_p, POINTER(ov_packet), ctypes.c_size_t, PACKET_CB, c_void_p]
    lib.ov_capture_start.restype  = c_int
    lib.ov_capture_dispatch.argtypes = [c_void_p, c_int]
    lib.ov_capture_dispatch.restype  = c_int
    lib.ov_capture_breakloop.argtypes = [c_void_p]
    lib.ov_capture_breakloop.restype  = None
    lib.ov_capture_stop.argtypes = [c_void_p]
    lib.ov_capture_stop.restype  = c_int
    lib.ov_get_error_string.argtypes = [c_void_p]
    lib.ov_get_error_string.restype  = c_char_p
    return lib


# ---- pcap framing --------------------------------------------------------

PCAP_NANOSEC_MAGIC = 0xa1b23c4d
LINKTYPE_USBLL     = 288
SNAPLEN            = 65535

PCAP_GLOBAL_HEADER = struct.pack(
    "<IHHIIII",
    PCAP_NANOSEC_MAGIC,
    2,                # version_major
    4,                # version_minor
    0,                # thiszone
    0,                # sigfigs
    SNAPLEN,
    LINKTYPE_USBLL,
)


# ---- capture state -------------------------------------------------------

@dataclass
class CaptureState:
    status: str = "idle"                       # idle | probing | locked | error
    locked_speed: Optional[str] = None
    probe_started_at: float = 0.0
    sof_seen: bool = False
    last_ov_ts: Optional[int] = None
    wall_ns_at_lock: Optional[int] = None
    packets_emitted: int = 0
    overflows: int = 0
    last_error: Optional[str] = None


class PcapBroadcaster:
    """In-process pcap fan-out. Each subscriber gets an `asyncio.Queue[bytes]`;
    queue contents are pcap records (and the pcap global header, once at
    session lock). Slow subscribers drop records rather than stall capture.

    All register/unregister/header operations run on the asyncio loop thread.
    `enqueue_record` is the only method called from the C thread, and it
    reaches the loop via `loop.call_soon_threadsafe` upstream.
    """

    MAX_QUEUE = 1024  # records; ~1 MB at max packet size

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue] = set()
        self._header_live = False

    def register(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(self.MAX_QUEUE)
        self._queues.add(q)
        if self._header_live:
            # Late-joining subscriber: prime with the global header so the
            # downstream parser (tshark) sees it before any record.
            q.put_nowait(PCAP_GLOBAL_HEADER)
        return q

    def unregister(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    def send_global_header(self) -> None:
        self._header_live = True
        for q in list(self._queues):
            try:
                q.put_nowait(PCAP_GLOBAL_HEADER)
            except asyncio.QueueFull:
                log.warning("pcap subscriber queue full at header send")

    def reset_header(self) -> None:
        self._header_live = False

    def enqueue_record(self, record: bytes) -> None:
        """Scheduled onto the loop thread via `call_soon_threadsafe` from the
        C packet callback. Touches `_queues` only — no lock needed since
        register/unregister also run on the loop thread."""
        for q in list(self._queues):
            try:
                q.put_nowait(record)
            except asyncio.QueueFull:
                log.warning("pcap subscriber slow, dropping record")


# ---- Supervisor ----------------------------------------------------------

class Supervisor:
    """In-process libopenvizsla supervisor, owned by the FastAPI app.

    Lifecycle (driven by `app.py`'s lifespan context manager):
      await supervisor.open()   # once at startup
      ...
      await supervisor.close()  # once at shutdown

    Per-session:
      await supervisor.start("ls"|"fs"|"hs")  -> {"ok": bool, "speed"?: str, "error"?: str}
      await supervisor.stop()                 -> {"ok": bool, "error"?: str}
      supervisor.status_dict()                -> dict
    """

    def __init__(self, probe_timeout: float = 2.0,
                 firmware: Optional[str] = None) -> None:
        self.probe_timeout = probe_timeout
        self.firmware_path = firmware

        self.lib: Optional[CDLL] = None
        self.state = CaptureState()
        self.state_lock = threading.Lock()

        self._ov: Optional[int] = None  # c_void_p as int
        self._capture_thread: Optional[threading.Thread] = None

        # Reusable packet buffer for ov_capture_start; libopenvizsla writes
        # into this same buffer repeatedly.
        self._buffer_size = OV_PACKET_HEADER_SIZE + OV_MAX_PACKET_SIZE + 16
        self._buffer = (c_uint8 * self._buffer_size)()

        # Pinned so GC doesn't collect the CFUNCTYPE wrapper while C holds it.
        self._callback: Optional[PACKET_CB] = None

        self.broadcaster: Optional[PcapBroadcaster] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ---- lifecycle ----

    async def open(self) -> None:
        """Load the libopenvizsla shared library and initialize the pcap
        broadcaster. Does NOT claim the USB device — that happens at session
        start (see `start()`). This lets the FastAPI app boot on a host
        without an OV3 attached; the UI reports "no devices" until one is
        plugged in and Rescan is hit."""
        if self.lib is not None:
            raise RuntimeError("Supervisor.open() called twice")
        self._loop = asyncio.get_running_loop()
        self.lib = _load_libopenvizsla()
        self.broadcaster = PcapBroadcaster()

    async def close(self) -> None:
        with self.state_lock:
            running = self.state.status in ("probing", "locked")
        if running:
            try:
                await self.stop()
            except Exception:
                log.exception("stop() during supervisor close failed")
        # Defensive: if a capture was never torn down (e.g. crash path),
        # still release the device.
        self._device_close()
        self.lib = None

    # ---- device ----

    def _device_open(self) -> None:
        assert self.lib is not None
        fw = self.firmware_path.encode() if self.firmware_path else None
        ov = self.lib.ov_new(fw)
        if not ov:
            raise RuntimeError("ov_new() returned NULL (out of memory?)")
        if self.lib.ov_open(ov) < 0:
            err = self.lib.ov_get_error_string(ov) or b"unknown"
            self.lib.ov_free(ov)
            raise RuntimeError(f"ov_open failed: {err.decode(errors='replace')}")
        self._ov = ov
        log.info("libopenvizsla device opened, firmware=%s",
                 self.firmware_path or "<embedded>")

    def _device_close(self) -> None:
        if self._ov is not None and self.lib is not None:
            self.lib.ov_free(self._ov)
            self._ov = None

    # ---- packet callback (runs on libopenvizsla's libusb thread) ----

    def _make_callback(self) -> PACKET_CB:
        # Closures pinned here are used from the C thread. Keeping
        # references as locals avoids one attribute lookup per packet.
        state = self.state
        state_lock = self.state_lock
        loop = self._loop
        broadcaster = self.broadcaster
        buffer_addr = ctypes.addressof(self._buffer)

        def cb(pkt_ptr, _user) -> None:
            try:
                p = pkt_ptr.contents
                flags = p.flags
                size = p.size
                ts = p.timestamp

                with state_lock:
                    if flags & OV_FLAGS_HF0_OVF:
                        state.overflows += 1

                captured_len = OV_MAX_PACKET_SIZE if (flags & OV_FLAGS_HF0_TRUNC) else size
                data = ctypes.string_at(buffer_addr + OV_PACKET_HEADER_SIZE, captured_len)

                # Lock signal: any valid packet. USB LS has no SOFs (host
                # sends EOP keep-alives instead); a successfully decoded
                # ov_packet implies the PHY is synced at this speed — good
                # enough for all three speeds.
                with state_lock:
                    phase = state.status
                    if not state.sof_seen and not (flags & OV_FLAGS_HF0_ERR):
                        state.sof_seen = True

                if phase != "locked":
                    return

                # Lazy-anchor wall + OV clocks on the first post-lock packet.
                with state_lock:
                    if state.last_ov_ts is None:
                        state.last_ov_ts = ts
                        state.wall_ns_at_lock = time.time_ns()
                    anchor_ov = state.last_ov_ts
                    anchor_wall = state.wall_ns_at_lock

                delta_ticks = (ts - anchor_ov) & 0xFFFFFFFFFFFFFFFF
                delta_ns = delta_ticks * 1_000_000_000 // OV_TIMESTAMP_FREQ_HZ
                abs_ns = anchor_wall + delta_ns
                ts_sec  = abs_ns // 1_000_000_000
                ts_nsec = abs_ns %  1_000_000_000

                record = struct.pack("<IIII", ts_sec, ts_nsec,
                                     captured_len, size) + data

                with state_lock:
                    state.packets_emitted += 1

                loop.call_soon_threadsafe(broadcaster.enqueue_record, record)
            except Exception as e:  # last-line defence: never raise into C
                log.exception("packet callback failed: %s", e)

        return PACKET_CB(cb)

    # ---- capture thread ----

    def _start_capture_thread(self, speed_const: int) -> None:
        assert self.lib is not None and self._ov is not None
        if self.lib.ov_set_usb_speed(self._ov, speed_const) < 0:
            err = self.lib.ov_get_error_string(self._ov) or b"set_usb_speed"
            raise RuntimeError(err.decode(errors="replace"))

        self._callback = self._make_callback()
        pkt_ptr = ctypes.cast(ctypes.pointer(self._buffer), POINTER(ov_packet))
        if self.lib.ov_capture_start(self._ov, pkt_ptr, self._buffer_size,
                                     self._callback, None) < 0:
            err = self.lib.ov_get_error_string(self._ov) or b"capture_start"
            raise RuntimeError(err.decode(errors="replace"))

        ov = self._ov
        lib = self.lib

        def run() -> None:
            # count=0 -> run until ov_capture_breakloop.
            # Return codes: >=0 packet count, -2 clean exit via breakloop,
            # other negative is a real error.
            rc = lib.ov_capture_dispatch(ov, 0)
            if rc < 0 and rc != -2:
                err = lib.ov_get_error_string(ov) or b"dispatch"
                log.warning("capture dispatch returned %d: %s", rc,
                            err.decode(errors="replace"))
            lib.ov_capture_stop(ov)

        self._capture_thread = threading.Thread(
            target=run, name="ov-dispatch", daemon=True)
        self._capture_thread.start()

    def _stop_capture_thread(self) -> None:
        if self._capture_thread is None:
            return
        assert self.lib is not None and self._ov is not None
        self.lib.ov_capture_breakloop(self._ov)
        self._capture_thread.join(timeout=5.0)
        self._capture_thread = None
        self._callback = None

    # ---- public async API ----

    async def start(self, speed: str) -> dict:
        assert self.broadcaster is not None, "Supervisor.open() first"
        with self.state_lock:
            if self.state.status in ("probing", "locked"):
                return {"ok": False, "error": f"already {self.state.status}"}

        speeds: list[str]
        if speed == "auto":
            speeds = ["hs", "fs", "ls"]
        elif speed in SPEED_BY_NAME:
            speeds = [speed]
        else:
            return {"ok": False, "error": f"unknown speed {speed!r}"}

        # Open the libopenvizsla device lazily: if nothing was plugged in at
        # app startup, or a previous session freed the device, do it now.
        # A failure here (e.g. "unable to claim usb device") is reported to
        # the caller rather than crashing the process.
        if self._ov is None:
            try:
                self._device_open()
            except RuntimeError as e:
                return {"ok": False, "error": str(e)}

        for attempt in speeds:
            log.info("probing speed=%s", attempt)
            with self.state_lock:
                self.state.status = "probing"
                self.state.locked_speed = None
                self.state.sof_seen = False
                self.state.probe_started_at = time.monotonic()
                self.state.last_ov_ts = None
                self.state.wall_ns_at_lock = None
                self.state.last_error = None

            try:
                self._start_capture_thread(SPEED_BY_NAME[attempt])
            except RuntimeError as e:
                with self.state_lock:
                    self.state.status = "error"
                    self.state.last_error = str(e)
                return {"ok": False, "error": str(e)}

            deadline = time.monotonic() + self.probe_timeout
            locked = False
            while time.monotonic() < deadline:
                await asyncio.sleep(0.05)
                with self.state_lock:
                    if self.state.sof_seen:
                        locked = True
                        break

            if not locked:
                self._stop_capture_thread()
                continue

            # SOF seen. Commit: publish pcap global header first, then flip
            # state to "locked". The callback lazy-anchors wall/OV on the
            # first post-lock packet.
            with self.state_lock:
                self.state.last_ov_ts = None
                self.state.wall_ns_at_lock = None

            self.broadcaster.send_global_header()

            with self.state_lock:
                self.state.status = "locked"
                self.state.locked_speed = attempt

            log.info("capture locked at speed=%s", attempt)
            return {"ok": True, "speed": attempt}

        with self.state_lock:
            self.state.status = "idle"
            self.state.last_error = "no SOF at any speed"
        return {"ok": False, "error": "no SOF at any speed", "speed": "unknown"}

    async def stop(self) -> dict:
        assert self.broadcaster is not None
        with self.state_lock:
            was = self.state.status
        if was not in ("probing", "locked"):
            return {"ok": False, "error": f"not running (status={was})"}
        self._stop_capture_thread()
        with self.state_lock:
            self.state.status = "idle"
            self.state.locked_speed = None
        self.broadcaster.reset_header()
        # Release the USB device between sessions so another process (or a
        # future ov-api restart) can claim it without racing against us. The
        # FPGA bitstream gets re-sent on next ov_open which adds ~100 ms but
        # keeps the lifecycle clean.
        self._device_close()
        return {"ok": True}

    def status_dict(self) -> dict:
        with self.state_lock:
            return {
                "status": self.state.status,
                "locked_speed": self.state.locked_speed,
                "packets_emitted": self.state.packets_emitted,
                "overflows": self.state.overflows,
                "last_error": self.state.last_error,
            }
