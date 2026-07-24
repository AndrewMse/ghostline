import numpy as np
import pytest

from ghostline.analysis import LapTrace, ReferenceLine, compare, extract_lap, insights, project_lap
from ghostline.synthetic import FigureEight, fly_arrays
from ghostline.timing import find_gate, segment


@pytest.fixture(scope="module")
def laps(track: FigureEight, flight):
    t, pos, run = flight
    timed = segment(t, pos, run, [], find_gate(t, pos, run))
    return [extract_lap(t, pos, lap.t_start, lap.t_end) for lap in timed]


def test_extract_lap_starts_and_ends_on_the_boundaries():
    t = np.arange(0.0, 1.0, 0.1)
    pos = np.column_stack([t, np.zeros_like(t), np.zeros_like(t)])
    lap = extract_lap(t, pos, 0.25, 0.75)
    assert lap.t[0] == 0.0 and lap.t[-1] == pytest.approx(0.5)
    assert lap.pos[0, 0] == pytest.approx(0.25) and lap.pos[-1, 0] == pytest.approx(0.75)


def test_lap_against_itself_has_no_delta(laps):
    c = compare(laps[2], laps[2])
    assert np.abs(c.delta).max() < 1e-3  # resampling the reference costs well under a millisecond
    assert np.abs(c.lateral).max() < 0.05


def test_final_delta_is_the_lap_time_difference(laps):
    for lap in laps:
        c = compare(lap, laps[3])
        assert c.delta[-1] == pytest.approx(lap.duration - laps[3].duration, abs=1e-6)
        assert c.sectors_lap.sum() == pytest.approx(lap.duration, abs=1e-6)


def test_projection_survives_the_crossover(track, laps):
    """The figure-8 passes the same x/z twice per lap; s must never jump."""
    line = ReferenceLine(laps[3])
    for lap in laps:
        s = line.project(lap.pos)
        assert np.diff(s).max() < 5.0  # no jumps to the other half of the track
        assert s[-1] > 0.95 * line.length
    assert line.length == pytest.approx(track.length, rel=0.05)


def slowed(lap: LapTrace, s_from: float, s_to: float, factor: float) -> LapTrace:
    """The same path flown `factor` times slower between two distances."""
    seg = np.linalg.norm(np.diff(lap.pos, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    dt = np.diff(lap.t)
    mid = (s[:-1] + s[1:]) / 2
    dt = np.where((mid >= s_from) & (mid <= s_to), dt * factor, dt)
    return LapTrace(np.concatenate([[0.0], np.cumsum(dt)]), lap.pos.copy())


def test_time_loss_is_located_where_it_happened(laps):
    ref = laps[3]
    lap = slowed(ref, 200.0, 240.0, 1.5)
    lost = lap.duration - ref.duration
    c = compare(lap, ref)
    before = c.delta[c.s < 195].max()
    after = c.delta[c.s > 245].min()
    assert abs(before) < 0.02
    assert after == pytest.approx(lost, abs=0.02)

    (worst, *_) = insights(c)
    assert worst["kind"] == "loss"
    assert 190 <= worst["s_start"] and worst["s_end"] <= 250
    assert worst["time"] == pytest.approx(lost, abs=0.05)


def test_offsets_are_signed_right_and_up():
    t = np.linspace(0, 10, 101)
    ref = LapTrace(t, np.column_stack([np.zeros_like(t), np.zeros_like(t), t * 10]))  # heading +z
    lap = LapTrace(t, np.column_stack([np.full_like(t, 2.0), np.full_like(t, -1.0), t * 10]))
    c = compare(lap, ref)
    # Unity is x-right when facing +z, so +x is right of the line
    assert np.median(c.lateral) == pytest.approx(2.0)
    assert np.median(c.vertical) == pytest.approx(-1.0)


def test_project_lap_is_monotonic(laps):
    line = ReferenceLine(laps[0])
    s = project_lap(laps[4], line)
    assert np.all(np.diff(s) >= 0) and s[0] == 0.0 and s[-1] == line.length


def test_different_pilots_same_track(track):
    """A slower pilot on a different line still lines up with the reference."""
    t1, p1 = fly_arrays(track, 3, seed=1, skill=1.0, mistake_rate=0.0)
    t2, p2 = fly_arrays(track, 3, seed=2, skill=0.85, mistake_rate=0.0)
    run1, run2 = np.zeros(len(t1), int), np.zeros(len(t2), int)
    gate = find_gate(t1, p1, run1)
    fast = segment(t1, p1, run1, [], gate)[1]
    slow = segment(t2, p2, run2, [], gate)[1]
    c = compare(extract_lap(t2, p2, slow.t_start, slow.t_end), extract_lap(t1, p1, fast.t_start, fast.t_end))
    assert slow.duration > fast.duration
    assert c.delta[-1] == pytest.approx(slow.duration - fast.duration, abs=1e-6)
    assert np.abs(c.lateral).max() < 6.0
