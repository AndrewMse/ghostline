"""Velocidrone's local WebSocket.

Enable it in the game: Options → Main Settings → Websocket Communication, and
Websocket IMU for position data (Betaflight flight controller model only).

Wire quirks that matter here (from the community's reverse-engineered spec):

* The game listens on the machine's LAN IP only, never on 127.0.0.1.
* Every server frame is a *binary* frame holding UTF-8 JSON.
* Race-event values are strings ("3", "31.245", "True"); `imu` is all numbers.
* RFC pings with a payload corrupt the game's frame parser, so library pings
  are off and `{"command":"ping"}` keeps the connection alive instead.
* Only the newest client receives events.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

import websockets

from ..models import Event, GateCrossing, RaceEnd, RaceStart, Sample, TrackInfo
from .base import Source, lan_ip

log = logging.getLogger(__name__)


def _num(v) -> float:
    return float(v)


def _bool(v) -> bool:
    return str(v).lower() == "true"


class MessageParser:
    """Turns decoded Velocidrone frames into events. Pure, so it is easy to test."""

    def __init__(self, pilot: str | None = None):
        self.pilot = pilot
        self._last: tuple[int, int, bool] | None = None

    def parse(self, msg: dict) -> list[Event]:
        out: list[Event] = []
        if "imu" in msg:
            d = msg["imu"]
            out.append(Sample(
                t=_num(d["timestamp"]) / 1000.0,
                pos=(_num(d["PositionX"]), _num(d["PositionY"]), _num(d["PositionZ"])),
                vel=(_num(d["SpeedX"]), _num(d["SpeedY"]), _num(d["SpeedZ"])),
                att=(_num(d["AttitudeX"]), _num(d["AttitudeY"]), _num(d["AttitudeZ"]), _num(d["AttitudeW"])),
                gyro=(_num(d["pitch"]), _num(d["roll"]), _num(d["yaw"])),
            ))
        elif "racedata" in msg:
            entry = self._own_entry(msg["racedata"])
            if entry is not None:
                # Snapshots repeat every pilot's latest state; only a change is a crossing.
                key = (int(entry["lap"]), int(entry["gate"]), _bool(entry.get("finished", "False")))
                if key != self._last:
                    self._last = key
                    out.append(GateCrossing(lap=key[0], gate=key[1], race_time=_num(entry["time"]),
                                            finished=key[2]))
        elif "racestatus" in msg:
            action = str(msg["racestatus"].get("raceAction", "")).lower()
            if action == "start":
                self._last = None
                out.append(RaceStart())
            elif action == "abort":
                out.append(RaceEnd(aborted=True))
            elif action == "race finished":
                out.append(RaceEnd())
        elif "countdown" in msg:
            # The race clock starts at 0, not at "start"; re-anchor on GO.
            if str(msg["countdown"].get("countValue")) == "0":
                out.append(RaceStart())
        elif "session" in msg:
            name = msg["session"].get("trackName")
            if name:
                out.append(TrackInfo(name=str(name)))
        return out

    def _own_entry(self, racedata: dict) -> dict | None:
        if self.pilot:
            return racedata.get(self.pilot)
        if len(racedata) == 1:
            return next(iter(racedata.values()))
        return None  # multiplayer with no pilot name configured: can't tell which one is us


class VelocidroneSource(Source):
    sim = "velocidrone"

    def __init__(self, host: str | None = None, port: int = 60003, pilot: str | None = None,
                 keepalive_s: float = 5.0):
        super().__init__()
        self.keepalive_s = keepalive_s
        self.host = host or lan_ip()
        self.port = port
        self.url = f"ws://{self.host}:{port}/velocidrone"
        self.parser = MessageParser(pilot)
        self.detail = f"connecting to {self.url}"

    async def events(self) -> AsyncIterator[Event]:
        while True:
            try:
                async with websockets.connect(self.url, ping_interval=None, max_size=None,
                                              compression=None, open_timeout=3) as ws:
                    self.connected = True
                    self.detail = f"connected to {self.url}"
                    keepalive = asyncio.create_task(self._keepalive(ws, self.keepalive_s))
                    try:
                        async for frame in ws:
                            text = frame.decode("utf-8", "replace") if isinstance(frame, bytes) else frame
                            if not text.strip().startswith("{"):
                                continue  # the game's non-RFC pong, empty echoes
                            try:
                                msg = json.loads(text)
                            except json.JSONDecodeError:
                                continue
                            for event in self.parser.parse(msg):
                                yield event
                    finally:
                        keepalive.cancel()
            except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as exc:
                self.detail = f"{self.url}: {exc.__class__.__name__}; is Websocket Communication on?"
            self.connected = False
            await asyncio.sleep(2.0)

    @staticmethod
    async def _keepalive(ws, every: float) -> None:
        while True:
            await asyncio.sleep(every)
            await ws.send(json.dumps({"command": "ping"}))
