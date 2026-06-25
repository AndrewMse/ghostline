import dataclasses

import pytest

from ghostline.db import Database
from ghostline.models import GateCrossing, RaceStart, Reset, TrackInfo
from ghostline.recorder import Recorder
from ghostline.service import Coach
from ghostline.synthetic import fly


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    yield d
    d.close()


def make(db, sim="demo") -> Recorder:
    return Recorder(db, Coach(db), sim)


def test_zero_config_session(db, track):
    rec = make(db)
    rec.handle(TrackInfo(track.name))
    for s in fly(track, 5, seed=3, mistake_rate=0.0):
        rec.handle(s)
    rec.close_session()

    (session,) = db.sessions()
    assert session["track"] == track.name
    assert db.track(session["track_id"])["gate"] is not None  # found by itself
    laps = db.laps(session_id=session["id"])
    assert len(laps) == 5
    assert all(14 < lap["duration"] < 20 for lap in laps)
    assert [lap["number"] for lap in laps] == [1, 2, 3, 4, 5]


def test_live_delta_against_pb(db, track):
    rec = make(db)
    for s in fly(track, 3, seed=3, mistake_rate=0.0):
        rec.handle(s)
    snap = rec.snapshot()
    assert snap["timing"] == "virtual"
    assert snap["best"] is not None
    assert snap["lap"] is not None and snap["lap"]["delta"] is not None
    assert abs(snap["lap"]["delta"]) < 2.0


def test_liftoff_style_reset_starts_a_new_run(db, track):
    """Liftoff's clock restarts at 0 on reset. No lap may span the two runs."""
    rec = make(db, "liftoff")
    first = list(fly(track, 3, seed=1, mistake_rate=0.0))
    cut = len(first) * 2 // 3
    for s in first[:cut]:
        rec.handle(s)
    for s in fly(track, 3, seed=2, mistake_rate=0.0):  # t starts again at 0
        rec.handle(s)
    rec.close_session()

    (session,) = db.sessions()
    laps = db.laps(session_id=session["id"])
    assert {lap["run"] for lap in laps} == {0, 1}
    assert all(lap["duration"] < 20 for lap in laps)


def test_velocidrone_race_is_timed_natively(db, track):
    """Crossings carry race time; the recorder maps it onto the telemetry clock at GO."""
    rec = make(db, "velocidrone")
    samples = [dataclasses.replace(s, t=s.t + 500.0) for s in fly(track, 3, seed=4, mistake_rate=0.0)]
    rec.handle(RaceStart())
    rec.handle(samples[0])
    t_go = samples[0].t
    race_laps = [(1, 1, 3.0), (1, 2, 9.0), (2, 1, 19.5), (2, 2, 25.0), (3, 1, 36.0), (3, 2, 42.0)]
    pending = list(race_laps)
    for s in samples[1:]:
        rec.handle(s)
        while pending and t_go + pending[0][2] <= s.t:
            lap, gate, rt = pending.pop(0)
            rec.handle(GateCrossing(lap, gate, rt))
    rec.handle(GateCrossing(3, 3, 52.25, finished=True))
    rec.close_session()

    laps = db.laps(session_id=db.sessions()[0]["id"])
    assert [round(lap["duration"], 3) for lap in laps] == [16.5, 16.5, 16.25]
    assert all(lap["timing"] == "native" for lap in laps)
    assert laps[0]["splits"] == [pytest.approx(6.0)]
    assert db.track(laps[0]["track_id"])["gate"] is None  # no guessing when the sim times laps


def test_renaming_the_track_moves_the_live_session(db, track):
    rec = make(db)
    for s in list(fly(track, 2, seed=5))[:600]:
        rec.handle(s)
    rec.set_track("Friday bando")
    rec.handle(Reset())
    rec.close_session()
    (session,) = db.sessions()
    assert session["track"] == "Friday bando"


def test_tiny_sessions_are_discarded(db, track):
    rec = make(db)
    for s in list(fly(track, 1, seed=5))[:60]:
        rec.handle(s)
    rec.close_session()
    assert db.sessions() == []
