"""ov-api FastAPI app: REST + WebSocket over the in-process capture supervisor
and session DB.

The OV3 can only run one capture at a time, so there is at most one active
`LiveSession`. Starting a session while another is active returns 409. Since
Phase 4.6 the libopenvizsla supervisor runs inside this process; there are
no external sockets.

Env:
  OV_DB_PATH            (default: ./ovweb.sqlite)
  OV_UI_DIR             (default: <pkg>/ui)  static frontend; 404-tolerated
  SPEED_PROBE_TIMEOUT   (default: 2.0)       per-speed probe deadline in seconds
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sqlite3
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .capture import CaptureClient, CaptureError, Supervisor
from .capture import devices as capture_devices
from .db import open_db
from .live_ingest import Broadcaster, DEFAULT_CHANNELS, LiveSession

log = logging.getLogger("ovweb")


# --- app state -----------------------------------------------------------


class AppState:
    def __init__(self) -> None:
        self.db_path = os.environ.get("OV_DB_PATH", "./ovweb.sqlite")
        self.ui_dir = Path(os.environ.get("OV_UI_DIR") or _default_ui_dir())
        self.probe_timeout = float(os.environ.get("SPEED_PROBE_TIMEOUT", "2.0"))

        self.db: sqlite3.Connection | None = None
        self.supervisor: Supervisor | None = None
        self.capture: CaptureClient | None = None
        self.active_session: LiveSession | None = None
        self.active_broadcaster: Broadcaster | None = None


def _default_ui_dir() -> Path:
    return Path(__file__).parent / "ui"


state = AppState()


# --- lifespan ------------------------------------------------------------


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    state.db = open_db(state.db_path)
    state.supervisor = Supervisor(probe_timeout=state.probe_timeout)
    await state.supervisor.open()
    state.capture = CaptureClient(state.supervisor)
    log.info("ovweb started: db=%s probe_timeout=%.1fs",
             state.db_path, state.probe_timeout)
    try:
        yield
    finally:
        # Order matters: stop the active ingest first so it unsubscribes
        # from the pcap broadcaster, then close the supervisor (which stops
        # any residual capture thread and frees libopenvizsla), then close
        # the DB.
        if state.active_session is not None:
            with contextlib.suppress(Exception):
                await state.active_session.stop()
        if state.supervisor is not None:
            with contextlib.suppress(Exception):
                await state.supervisor.close()
        if state.db is not None:
            state.db.close()
        log.info("ovweb stopped")


app = FastAPI(title="ovweb", version="0.1.0", lifespan=lifespan)


# --- schemas -------------------------------------------------------------


class StartRequest(BaseModel):
    speed: str = Field(..., pattern="^(ls|fs|hs)$",
                       description="USB speed. Auto-retry deliberately not exposed "
                                   "yet; it wedges libopenvizsla between probes.")
    notes: str | None = None
    # Forward-compat hook for 4.7 when libopenvizsla gains device-by-serial
    # selection. For now the supervisor opens the first match regardless;
    # we log a warning if the caller supplied a serial while multiple boards
    # are attached so the UI's intent is visible in the logs.
    device_serial: str | None = None


class SessionSummary(BaseModel):
    id: int
    started_at: str
    ended_at: str | None
    speed: str
    status: str
    notes: str | None


class SessionDetail(SessionSummary):
    source_pcap: str | None
    endpoints: list[dict]
    transfer_count: int


class TransferRow(BaseModel):
    ts_ns: int
    device_addr: int
    ep_addr: int
    direction: str
    type: str
    status: str
    length: int
    setup_hex: str | None
    data_hex: str | None


# --- helpers -------------------------------------------------------------


def _row_to_summary(r: sqlite3.Row) -> SessionSummary:
    return SessionSummary(
        id=r["id"], started_at=r["started_at"], ended_at=r["ended_at"],
        speed=r["speed"], status=r["status"], notes=r["notes"],
    )


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


# --- routes --------------------------------------------------------------


@app.get("/api/sessions")
async def list_sessions() -> list[SessionSummary]:
    assert state.db is not None
    rows = state.db.execute(
        "SELECT id, started_at, ended_at, speed, status, notes FROM sessions "
        "ORDER BY id DESC LIMIT 200"
    ).fetchall()
    return [_row_to_summary(r) for r in rows]


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: int) -> SessionDetail:
    assert state.db is not None
    row = state.db.execute(
        "SELECT id, started_at, ended_at, speed, status, notes, source_pcap "
        "FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"session {session_id} not found")

    eps = [
        {"device_addr": e["device_addr"], "ep_addr": e["ep_addr"],
         "type": e["type"], "mps": e["mps"],
         "summary": json.loads(e["observed_summary_json"])}
        for e in state.db.execute(
            "SELECT device_addr, ep_addr, type, mps, observed_summary_json "
            "FROM endpoints WHERE session_id = ? ORDER BY device_addr, ep_addr",
            (session_id,),
        )
    ]
    n = state.db.execute(
        "SELECT COUNT(*) n FROM transfers WHERE session_id = ?", (session_id,)
    ).fetchone()["n"]
    return SessionDetail(
        **_row_to_summary(row).model_dump(),
        source_pcap=row["source_pcap"],
        endpoints=eps,
        transfer_count=int(n),
    )


@app.get("/api/sessions/{session_id}/transfers")
async def get_transfers(session_id: int, offset: int = 0, limit: int = 200) -> list[TransferRow]:
    assert state.db is not None
    limit = max(1, min(limit, 2000))
    rows = state.db.execute(
        "SELECT ts_ns, device_addr, ep_addr, direction, type, status, length, "
        "setup_bytes, data_bytes FROM transfers WHERE session_id = ? "
        "ORDER BY ts_ns LIMIT ? OFFSET ?",
        (session_id, limit, offset),
    ).fetchall()
    out: list[TransferRow] = []
    for r in rows:
        out.append(TransferRow(
            ts_ns=r["ts_ns"], device_addr=r["device_addr"], ep_addr=r["ep_addr"],
            direction=r["direction"], type=r["type"], status=r["status"],
            length=r["length"],
            setup_hex=r["setup_bytes"].hex() if r["setup_bytes"] else None,
            data_hex=r["data_bytes"].hex() if r["data_bytes"] else None,
        ))
    return out


@app.get("/api/devices")
async def list_devices() -> dict[str, Any]:
    """Enumerate attached OpenVizsla 3 candidates (both the OpenMoko EEPROM
    `1d50:607c` and the raw-FTDI `0403:6010` fallback). Used by the UI
    device picker. The `selected_policy` field documents what the supervisor
    will actually do on session start — today libopenvizsla grabs the first
    match; picking by serial is tracked as Phase 4.7."""
    try:
        devs = capture_devices.enumerate()
    except Exception as e:  # noqa: BLE001
        log.exception("device enumeration failed: %s", e)
        raise HTTPException(500, f"device enumeration failed: {e}") from e
    return {
        "devices": [d.to_dict() for d in devs],
        "selected_policy": "first-match",
    }


@app.post("/api/sessions", status_code=201)
async def start_session(req: StartRequest) -> dict[str, Any]:
    assert state.db is not None and state.capture is not None
    if state.active_session is not None:
        raise HTTPException(409, "another capture is already running")

    # Preflight: at least one OV3 must be attached, else a friendly 400
    # beats libopenvizsla's opaque "ov_open failed: device not found". The
    # caller's optional device_serial is forward-compat only for 4.6; the
    # supervisor still picks the first match regardless of what's specified.
    devs = capture_devices.enumerate()
    if not devs:
        raise HTTPException(400, "no OpenVizsla 3 attached; plug one in and retry")
    if req.device_serial and len(devs) > 1:
        picked = devs[0]
        if req.device_serial != picked.serial:
            log.warning("device_serial=%r requested but libopenvizsla will open "
                        "the first match (serial=%r); selection-by-serial lands in 4.7",
                        req.device_serial, picked.serial)

    try:
        locked_speed = await state.capture.start(req.speed)
    except CaptureError as e:
        raise HTTPException(502, f"capture daemon: {e}") from e

    cur = state.db.execute(
        "INSERT INTO sessions (started_at, status, speed, notes) "
        "VALUES (?, 'live', ?, ?)",
        (_utcnow(), locked_speed, req.notes),
    )
    session_id = int(cur.lastrowid)

    assert state.supervisor is not None
    broadcaster = Broadcaster()
    live = LiveSession(session_id, state.supervisor, state.db, broadcaster)
    await live.start()
    state.active_session = live
    state.active_broadcaster = broadcaster

    return {"session_id": session_id, "speed": locked_speed}


@app.post("/api/sessions/{session_id}/stop")
async def stop_session(session_id: int) -> dict[str, Any]:
    assert state.db is not None and state.capture is not None
    live = state.active_session
    if live is None or live.session_id != session_id:
        raise HTTPException(409, f"session {session_id} is not the active session")

    with contextlib.suppress(CaptureError):
        await state.capture.stop()
    await live.stop()
    state.active_session = None
    state.active_broadcaster = None

    state.db.execute(
        "UPDATE sessions SET ended_at = ?, status = 'closed' WHERE id = ?",
        (_utcnow(), session_id),
    )
    _rebuild_endpoint_summary(state.db, session_id)
    return {"session_id": session_id,
            "packets": live.packets_seen,
            "transfers": live.transfers_seen}


def _rebuild_endpoint_summary(db: sqlite3.Connection, session_id: int) -> None:
    """Aggregate transfers -> endpoints rows. Same shape as decode-session's
    summary so the REST detail response is consistent whether the session
    came from live capture or a decoded pcap."""
    rows = db.execute(
        "SELECT device_addr, ep_addr, direction, status, length "
        "FROM transfers WHERE session_id = ?", (session_id,),
    ).fetchall()
    agg: dict[tuple[int, int], dict] = {}
    for r in rows:
        key = (r["device_addr"], r["ep_addr"])
        s = agg.setdefault(key, {
            "in": 0, "out": 0, "setup": 0,
            "ack": 0, "nak": 0, "stall": 0, "nyet": 0, "incomplete": 0,
            "max_data_len": 0, "has_setup": False,
        })
        if r["direction"] in ("in", "out", "setup"):
            s[r["direction"]] += 1
        if r["status"] in ("ack", "nak", "stall", "nyet", "incomplete"):
            s[r["status"]] += 1
        if r["length"] > s["max_data_len"]:
            s["max_data_len"] = r["length"]
        if r["direction"] == "setup":
            s["has_setup"] = True
    for (addr, ep), s in sorted(agg.items()):
        xtype = "control" if s.pop("has_setup") else "bulk_or_interrupt"
        max_len = s["max_data_len"]
        db.execute(
            "INSERT OR REPLACE INTO endpoints "
            "(session_id, device_addr, ep_addr, type, mps, observed_summary_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, addr, ep, xtype, max_len,
             json.dumps(s, sort_keys=True)),
        )


@app.websocket("/api/sessions/{session_id}/live")
async def live_feed(ws: WebSocket, session_id: int) -> None:
    """Three-channel live feed.

    On connect the server sends a hello with the initial endpoint snapshot.
    The client is opted into `summary + events` by default; it can resubscribe
    with `{"type":"subscribe","channels":[...]}` to add or drop `firehose`
    (the raw per-transfer stream). Every message from the server is one of:

      {"type":"endpoint_update","updates":[...]}   — summary channel
      {"type":"event","kind":"...","...":...}       — events channel
      {"type":"transfer","transfer":{...}}           — firehose channel
      {"type":"end","packets":...,"transfers":...}   — all subscribers
      {"type":"error","error":"..."}                 — all subscribers
    """
    await ws.accept()
    live = state.active_session
    broadcaster = state.active_broadcaster
    if live is None or broadcaster is None or live.session_id != session_id:
        await ws.send_json({"type": "error", "error": "not-the-active-session"})
        await ws.close(code=1008)
        return

    q = broadcaster.subscribe()  # default: summary + events

    # Tell the client what it's subscribed to and prime its endpoint table
    # with whatever's already in flight — avoids a blank pane until the
    # next summary tick.
    await ws.send_json({
        "type": "hello",
        "session_id": session_id,
        "channels_default": sorted(DEFAULT_CHANNELS),
        "snapshot": {"endpoints": live.filter.snapshot()},
    })

    async def pump_out() -> None:
        try:
            while True:
                msg = await q.get()
                await ws.send_json(msg)
                if msg.get("type") == "end":
                    return
        except WebSocketDisconnect:
            return

    async def pump_in() -> None:
        # Handle client -> server control messages. Only recognized command:
        # "subscribe" with a `channels` list. Unknown messages are ignored.
        try:
            while True:
                msg = await ws.receive_json()
                if msg.get("type") == "subscribe":
                    chans = msg.get("channels") or []
                    broadcaster.set_channels(q, set(chans))
        except WebSocketDisconnect:
            return
        except Exception as e:  # noqa: BLE001
            log.debug("ws control channel closed: %s", e)
            return

    out_task = asyncio.create_task(pump_out())
    in_task = asyncio.create_task(pump_in())
    try:
        done, pending = await asyncio.wait(
            {out_task, in_task}, return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        broadcaster.unsubscribe(q)
        with contextlib.suppress(Exception):
            await ws.close()


# --- static UI + SPA fallback -------------------------------------------


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "time": _utcnow()}


# Mount static UI if the build output is available. In dev you can run the
# Svelte dev server on :5173 and set OV_UI_DIR to its `dist/` when you
# `pnpm build`. Missing UI is not fatal.
if state.ui_dir.exists():
    app.mount("/", StaticFiles(directory=str(state.ui_dir), html=True), name="ui")
else:
    log.warning("ui dir %s does not exist; static UI not mounted", state.ui_dir)

    @app.get("/")
    async def _ui_placeholder() -> JSONResponse:
        return JSONResponse(
            {"ok": True,
             "hint": "UI not built yet. Run `pnpm build` in frontend/ or set OV_UI_DIR."},
            status_code=200,
        )
