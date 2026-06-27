import pytest
from fastapi.testclient import TestClient

from ghostline.db import Database
from ghostline.main import create_app
from ghostline.models import TrackInfo
from ghostline.recorder import Recorder
from ghostline.service import Coach
from ghostline.synthetic import fly


@pytest.fixture(scope="module")
def client(tmp_path_factory, track):
    path = tmp_path_factory.mktemp("api") / "api.db"
    db = Database(path)
    rec = Recorder(db, Coach(db), "demo")
    for k in range(2):
        rec.handle(TrackInfo(track.name))
        for s in fly(track, 4, seed=20 + k):
            rec.handle(s)
        rec.close_session()
    db.close()
    with TestClient(create_app(str(path))) as c:
        yield c


def test_tracks_and_summary(client):
    (track,) = client.get("/api/tracks").json()
    assert track["laps"] == 8 and track["gate"] is not None
    summary = client.get(f"/api/tracks/{track['id']}").json()
    assert summary["best_lap"]["duration"] == pytest.approx(track["best"])
    assert summary["theoretical_best"] <= summary["best_lap"]["duration"] + 1e-6
    assert len(summary["sector_bounds"]) == 7
    assert all(len(lap["sectors"]) == 6 for lap in summary["laps"])


def test_compare(client):
    summary = client.get("/api/tracks/1").json()
    best = summary["best_lap"]["id"]
    other = next(lap for lap in summary["laps"] if lap["id"] != best)
    r = client.get(f"/api/compare?lap={other['id']}&ref={best}").json()
    n = len(r["s"])
    assert all(len(r[k]) == n for k in ("delta", "speed_lap", "speed_ref", "lateral", "pos_lap", "pos_ref"))
    assert r["delta"][-1] == pytest.approx(other["duration"] - summary["best_lap"]["duration"], abs=1e-3)
    assert sum(s["delta"] for s in r["sectors"]) == pytest.approx(r["delta"][-1], abs=5e-3)


def test_sessions_laps_and_path(client):
    sessions = client.get("/api/sessions").json()
    assert len(sessions) == 2
    detail = client.get(f"/api/sessions/{sessions[0]['id']}").json()
    assert len(detail["laps"]) == 4
    lap = client.get(f"/api/laps/{detail['laps'][0]['id']}").json()
    assert len(lap["t"]) == len(lap["pos"]) == len(lap["speed"]) > 100
    assert lap["sticks"] is not None
    path = client.get(f"/api/sessions/{sessions[0]['id']}/path?hz=5").json()
    assert 0 < len(path["pos"]) < len(lap["t"]) * 3


def test_move_gate_by_hand_retimes_every_session(client):
    session = client.get("/api/sessions").json()[-1]
    lap = client.get(f"/api/sessions/{session['id']}").json()["laps"][1]
    # Put the gate half way round the lap instead.
    mid = (lap["t_start"] + lap["t_end"]) / 2
    r = client.put("/api/tracks/1/gate", json={"session_id": session["id"], "t": mid})
    assert r.status_code == 200
    moved = client.get("/api/tracks/1").json()
    # 4 laps from a standing start per session; a mid-lap line leaves 3 whole laps in each.
    assert moved["stats"]["laps"] == 6
    assert client.post("/api/tracks/1/gate/detect", json={}).status_code == 200
    assert client.get("/api/tracks/1").json()["stats"]["laps"] == 8


def test_errors(client):
    assert client.get("/api/laps/9999").status_code == 404
    assert client.get("/api/compare?lap=1&ref=9999").status_code == 404
    assert client.patch("/api/tracks/1", json={"name": ""}).status_code == 422
    assert client.post("/api/live/track", json={"name": "x"}).status_code == 404  # no live source
