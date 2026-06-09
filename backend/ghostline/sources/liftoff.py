"""Liftoff's UDP telemetry stream.

Liftoff sends one UDP datagram per physics frame to the endpoint named in
`TelemetryConfiguration.json`. Each datagram is the fields listed in
`StreamFormat`, in that order, as little-endian float32s; `MotorRPM` is a
one-byte motor count followed by that many floats. Timestamp resets to zero
when the drone is reset.
"""

from __future__ import annotations

import asyncio
import json
import platform
import struct
from pathlib import Path
from typing import AsyncIterator, Sequence

from ..models import Event, Sample
from .base import Source

STREAM_FORMAT = ["Timestamp", "Position", "Attitude", "Velocity", "Gyro", "Input"]
FLOATS = {"Timestamp": 1, "Position": 3, "Attitude": 4, "Velocity": 3, "Gyro": 3, "Input": 4, "Battery": 2}


def parse_datagram(data: bytes, fmt: Sequence[str] = STREAM_FORMAT) -> Sample:
    fields: dict[str, tuple[float, ...]] = {}
    off = 0
    for name in fmt:
        if name == "MotorRPM":
            count = data[off]
            off += 1
            fields[name] = struct.unpack_from(f"<{count}f", data, off)
            off += 4 * count
        else:
            n = FLOATS[name]
            fields[name] = struct.unpack_from(f"<{n}f", data, off)
            off += 4 * n
    sticks = None
    if "Input" in fields:
        throttle, yaw, pitch, roll = fields["Input"]
        # Liftoff sends throttle as -1 (idle) .. 1 (full).
        sticks = (min(max((throttle + 1) / 2, 0.0), 1.0), yaw, pitch, roll)
    return Sample(
        t=fields["Timestamp"][0],
        pos=fields["Position"],
        vel=fields.get("Velocity"),
        att=fields.get("Attitude"),
        gyro=fields.get("Gyro"),
        sticks=sticks,
    )


def config_path() -> Path:
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return home / "Library/Application Support/LuGus Studios/Liftoff/TelemetryConfiguration.json"
    if system == "Windows":
        return home / "AppData/LocalLow/LuGus Studios/Liftoff/TelemetryConfiguration.json"
    return home / ".config/unity3d/LuGus Studios/Liftoff/TelemetryConfiguration.json"


def config_json(host: str = "127.0.0.1", port: int = 9001) -> str:
    return json.dumps({"EndPoint": f"{host}:{port}", "StreamFormat": STREAM_FORMAT}, indent=2)


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue[bytes]):
        self.queue = queue

    def datagram_received(self, data: bytes, addr) -> None:
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(data)


class LiftoffSource(Source):
    sim = "liftoff"

    def __init__(self, host: str = "127.0.0.1", port: int = 9001, fmt: Sequence[str] = STREAM_FORMAT):
        super().__init__()
        self.host, self.port, self.fmt = host, port, list(fmt)
        self.detail = f"listening on udp://{host}:{port}"

    async def events(self) -> AsyncIterator[Event]:
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2000)
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _Protocol(queue), local_addr=(self.host, self.port))
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=2.0)
                except asyncio.TimeoutError:
                    self.connected = False
                    continue
                try:
                    sample = parse_datagram(data, self.fmt)
                except (struct.error, IndexError, KeyError):
                    self.detail = "datagram does not match StreamFormat; check TelemetryConfiguration.json"
                    continue
                self.connected = True
                yield sample
        finally:
            transport.close()
