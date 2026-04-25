"""In-process client over a local `Supervisor` instance.

Historically this was a newline-JSON RPC client against the ov-capture
sidecar's control.sock. Phase 4.6 merged the supervisor into the ov-api
process; the client now wraps a `Supervisor` directly but keeps the public
method shapes (`.start(speed) -> str`, `.stop() -> None`, `.status() ->
CaptureStatus`) so `app.py`'s call sites need no changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .supervisor import Supervisor


class CaptureError(RuntimeError):
    """Raised on capture failures (start refused, device error, etc)."""


@dataclass(slots=True)
class CaptureStatus:
    status: str                     # 'idle' | 'probing' | 'locked' | 'error'
    locked_speed: str | None
    packets_emitted: int
    overflows: int
    last_error: str | None


class CaptureClient:
    def __init__(self, supervisor: Supervisor) -> None:
        self._sup = supervisor

    async def start(self, speed: str) -> str:
        """Returns the locked speed (e.g. 'hs', 'ls') on success."""
        r = await self._sup.start(speed)
        if not r.get("ok"):
            raise CaptureError(r.get("error", "start failed"))
        return str(r.get("speed", speed))

    async def stop(self) -> None:
        r = await self._sup.stop()
        if not r.get("ok"):
            err = r.get("error", "")
            # "not running" is not an error from the API's perspective —
            # matches the supervisor's behaviour when stop() races with an
            # already-stopped capture.
            if "not running" not in err:
                raise CaptureError(err)

    async def status(self) -> CaptureStatus:
        return CaptureStatus(**self._sup.status_dict())
