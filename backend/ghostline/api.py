from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .db import Database
from .recorder import Recorder
from .service import Coach

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class TrackName(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class GateFromPath(BaseModel):
    session_id: int
    t: float
    radius: float = Field(default=6.0, gt=0.5, le=30.0)


class DetectGate(BaseModel):
    session_id: int | None = None


def _db(request: Request) -> Database:
    return request.app.state.db


def _coach(request: Request) -> Coach:
    return request.app.state.coach


def _recorder(request: Request) -> Recorder | None:
    return request.app.state.recorder


def _found(value, what: str):
    if value is None:
        raise HTTPException(404, f"{what} not found")
    return value


def _gate_changed(request: Request, track_id: int) -> None:
    _coach(request).resegment_track(track_id)
    rec = _recorder(request)
    if rec is not None and rec.track_id == track_id:
        rec.retime()


@router.get("/status")
def status(request: Request) -> dict:
    source = request.app.state.source
    rec = _recorder(request)
    return {
        "source": source.status() if source else None,
        "live": rec.snapshot() if rec else None,
    }


@router.get("/tracks")
def tracks(request: Request) -> list[dict]:
    return _db(request).tracks()


@router.get("/tracks/{track_id}")
def track(request: Request, track_id: int, sectors: int = 6) -> dict:
    return _found(_coach(request).track_summary(track_id, sectors), "track")


@router.patch("/tracks/{track_id}")
def rename_track(request: Request, track_id: int, body: TrackName) -> dict:
    db = _db(request)
    _found(db.track(track_id), "track")
    db.rename_track(track_id, body.name)
    rec = _recorder(request)
    if rec is not None and rec.track_id == track_id:
        rec.track_name = body.name
    return db.track(track_id)


@router.put("/tracks/{track_id}/gate")
def set_gate(request: Request, track_id: int, body: GateFromPath) -> dict:
    db = _db(request)
    _found(db.track(track_id), "track")
    gate = _coach(request).gate_at(body.session_id, body.t, body.radius)
    if gate is None:
        raise HTTPException(422, "the drone was not moving there; pick a point on the racing line")
    db.set_track_gate(track_id, gate)
    _gate_changed(request, track_id)
    return db.track(track_id)


@router.post("/tracks/{track_id}/gate/detect")
def detect_gate(request: Request, track_id: int, body: DetectGate) -> dict:
    db = _db(request)
    _found(db.track(track_id), "track")
    session_id = body.session_id
    if session_id is None:
        sessions = db.sessions(track_id)
        if not sessions:
            raise HTTPException(422, "no sessions on this track yet")
        session_id = sessions[0]["id"]
    gate = _coach(request).detect_gate(session_id)
    if gate is None:
        raise HTTPException(422, "couldn't find a start/finish line; fly a few more laps or set it by hand")
    db.set_track_gate(track_id, gate)
    _gate_changed(request, track_id)
    return db.track(track_id)


@router.delete("/tracks/{track_id}/gate")
def clear_gate(request: Request, track_id: int) -> dict:
    db = _db(request)
    _found(db.track(track_id), "track")
    db.set_track_gate(track_id, None)
    _gate_changed(request, track_id)
    return db.track(track_id)


@router.get("/sessions")
def sessions(request: Request, track_id: int | None = None) -> list[dict]:
    return _db(request).sessions(track_id)


@router.get("/sessions/{session_id}")
def session(request: Request, session_id: int) -> dict:
    db = _db(request)
    s = _found(db.session(session_id), "session")
    return {**s, "laps": db.laps(session_id=session_id)}


@router.get("/sessions/{session_id}/path")
def session_path(request: Request, session_id: int, hz: float = 10.0) -> dict:
    _found(_db(request).session(session_id), "session")
    return _coach(request).session_path(session_id, min(max(hz, 1.0), 60.0))


@router.patch("/sessions/{session_id}")
def move_session(request: Request, session_id: int, body: TrackName) -> dict:
    """Assign the session to a track by name (created if new), and re-time it."""
    db = _db(request)
    s = _found(db.session(session_id), "session")
    rec = _recorder(request)
    if rec is not None and rec.session_id == session_id:
        rec.set_track(body.name)
    else:
        db.set_session_track(session_id, db.track_id(body.name, s["sim"]))
        _coach(request).resegment_session(session_id)
    return {**db.session(session_id), "laps": db.laps(session_id=session_id)}


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(request: Request, session_id: int) -> None:
    db = _db(request)
    _found(db.session(session_id), "session")
    rec = _recorder(request)
    if rec is not None and rec.session_id == session_id:
        raise HTTPException(409, "that session is still recording")
    db.delete_session(session_id)


@router.get("/laps/{lap_id}")
def lap(request: Request, lap_id: int) -> dict:
    return _found(_coach(request).lap_detail(lap_id), "lap")


@router.get("/compare")
def compare(request: Request, lap: int, ref: int, sectors: int = 6) -> dict:
    return _found(_coach(request).compare(lap, ref, min(max(sectors, 1), 20)), "lap")


@router.post("/live/track")
def live_track(request: Request, body: TrackName) -> dict:
    rec = _found(_recorder(request), "live recorder")
    rec.set_track(body.name)
    return rec.snapshot()


@router.websocket("/live")
async def live(ws: WebSocket) -> None:
    await ws.accept()
    app = ws.app
    try:
        while True:
            rec = app.state.recorder
            source = app.state.source
            await ws.send_json({
                "source": source.status() if source else None,
                "live": rec.snapshot() if rec else None,
            })
            await asyncio.sleep(1 / 15)
    except (WebSocketDisconnect, RuntimeError):
        pass
