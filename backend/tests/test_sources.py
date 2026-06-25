import asyncio
import json
import struct

import pytest
import websockets

from ghostline.models import GateCrossing, RaceEnd, RaceStart, Sample, TrackInfo
from ghostline.sources.liftoff import STREAM_FORMAT, parse_datagram
from ghostline.sources.velocidrone import MessageParser, VelocidroneSource


def pack(*groups):
    return b"".join(struct.pack(f"<{len(g)}f", *g) for g in groups)


def test_liftoff_default_format():
    data = pack([12.5], [1, 2, 3], [0, 0, 0, 1], [4, 5, 6], [10, 20, 30], [0.0, 0.1, -0.2, 0.3])
    s = parse_datagram(data, STREAM_FORMAT)
    assert s.t == 12.5
    assert s.pos == (1, 2, 3)
    assert s.att == (0, 0, 0, 1)
    assert s.vel == (4, 5, 6)
    assert s.gyro == (10, 20, 30)
    # throttle -1..1 becomes 0..1; the other sticks pass through
    assert s.sticks[0] == pytest.approx(0.5)
    assert s.sticks[1:] == pytest.approx((0.1, -0.2, 0.3))


def test_liftoff_custom_order_with_motor_rpm():
    fmt = ["Position", "MotorRPM", "Timestamp"]
    data = pack([1, 2, 3]) + bytes([4]) + pack([100, 200, 300, 400]) + pack([7.0])
    s = parse_datagram(data, fmt)
    assert s.pos == (1, 2, 3)
    assert s.t == 7.0
    assert s.sticks is None and s.vel is None


IMU = {"imu": {"roll": 1.0, "pitch": 2.0, "yaw": 3.0, "PositionX": 10.0, "PositionY": 2.0, "PositionZ": -5.0,
               "AttitudeX": 0.0, "AttitudeY": 0.0, "AttitudeZ": 0.0, "AttitudeW": 1.0,
               "SpeedX": 1.0, "SpeedY": 0.0, "SpeedZ": 0.0, "timestamp": 123456.0}}


def racedata(lap, gate, time, finished="False", name="Me"):
    return {"racedata": {name: {"position": "1", "lap": str(lap), "gate": str(gate), "time": f"{time:.3f}",
                                "finished": finished, "colour": "00FFFF", "uid": 1}}}


def test_velocidrone_imu():
    (s,) = MessageParser().parse(IMU)
    assert isinstance(s, Sample)
    assert s.t == pytest.approx(123.456)
    assert s.pos == (10.0, 2.0, -5.0)
    assert s.gyro == (2.0, 1.0, 3.0)  # stored as pitch, roll, yaw
    assert s.sticks is None


def test_velocidrone_race_events():
    p = MessageParser()
    assert p.parse({"racestatus": {"raceAction": "start"}}) == [RaceStart()]
    assert p.parse({"countdown": {"countValue": "1"}}) == []
    assert p.parse({"countdown": {"countValue": "0"}}) == [RaceStart()]
    assert p.parse(racedata(1, 1, 1.5)) == [GateCrossing(1, 1, 1.5, False)]
    # snapshots repeat when other pilots cross; only changes are crossings
    assert p.parse(racedata(1, 1, 1.5)) == []
    assert p.parse(racedata(1, 2, 3.25)) == [GateCrossing(1, 2, 3.25, False)]
    assert p.parse(racedata(3, 9, 60.0, "True")) == [GateCrossing(3, 9, 60.0, True)]
    assert p.parse(racedata(3, 9, 60.0, "True")) == []
    assert p.parse({"racestatus": {"raceAction": "race finished"}}) == [RaceEnd()]
    assert p.parse({"session": {"trackName": "Bando"}}) == [TrackInfo("Bando")]
    assert p.parse({"spectatorChange": "Someone"}) == []


def test_velocidrone_multiplayer_needs_pilot_name():
    both = {"racedata": {**racedata(1, 1, 1.0, name="A")["racedata"], **racedata(1, 2, 1.1, name="B")["racedata"]}}
    assert MessageParser().parse(both) == []
    assert MessageParser(pilot="B").parse(both) == [GateCrossing(1, 2, 1.1, False)]


async def test_velocidrone_source_against_fake_game():
    """Binary JSON frames in, events out, and the game-style keepalive goes back."""
    received: list[str] = []

    async def game(ws):
        await ws.send(json.dumps(IMU).encode())  # the game only sends binary frames
        await ws.send(bytes([0x8A, 0x00]))  # its non-standard pong: must be ignored
        await ws.send(json.dumps(racedata(1, 1, 0.5)).encode())
        try:
            async for msg in ws:
                received.append(msg)
        except websockets.ConnectionClosed:
            pass

    async with websockets.serve(game, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        source = VelocidroneSource("127.0.0.1", port, keepalive_s=0.05)
        events = []

        async def collect():
            async for e in source.events():
                events.append(e)
                if len(events) == 2:
                    await asyncio.sleep(0.2)  # let a keepalive go out
                    return

        await asyncio.wait_for(collect(), 5)
    assert isinstance(events[0], Sample)
    assert events[1] == GateCrossing(1, 1, 0.5, False)
    assert json.loads(received[0]) == {"command": "ping"}
