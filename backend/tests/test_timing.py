import numpy as np
import pytest

from ghostline.models import GateCrossing
from ghostline.timing import LapTimer, VirtualGate, find_gate, lap_times_through, segment

GATE = VirtualGate(center=(0.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0), radius=3.0)


def test_crossing_is_interpolated_between_frames():
    assert GATE.crossing(1.0, (0, 0, -1), 2.0, (0, 0, 3)) == pytest.approx(1.25)


def test_crossing_only_forwards_and_inside_radius():
    assert GATE.crossing(0.0, (0, 0, 1), 1.0, (0, 0, -1)) is None  # backwards
    assert GATE.crossing(0.0, (5, 0, -1), 1.0, (5, 0, 1)) is None  # outside the gate
    assert GATE.crossing(0.0, (0, 0, 1), 1.0, (0, 0, 2)) is None  # never crosses


def circle(laps: float, period: float = 10.0, hz: float = 60.0, radius: float = 20.0):
    """Anticlockwise circle through the gate at (0,0,0) heading +z, starting just behind it."""
    t = np.arange(0, laps * period, 1 / hz)
    a = 2 * np.pi * t / period - 0.2
    pos = np.column_stack([radius * (1 - np.cos(a)), np.zeros_like(a), radius * np.sin(a)])
    return t, pos


def test_virtual_laps_on_a_circle():
    t, pos = circle(4.2)
    t = t + 0.37  # timing must not depend on where the clock started
    laps = segment(t, pos, np.zeros(len(t), int), [], GATE)
    assert [round(lap.duration, 6) for lap in laps] == [10.0] * 4
    assert all(lap.timing == "virtual" for lap in laps)


def test_laps_never_span_a_reset():
    t, pos = circle(4.2)
    run = (t > 25.0).astype(int)  # reset in the middle of lap 3
    laps = segment(t, pos, run, [], GATE)
    assert [lap.run for lap in laps] == [0, 0, 1]


def test_native_race_with_holeshot_splits_and_finish():
    timer = LapTimer(GATE)
    events = [
        (1.0, GateCrossing(0, 1, 1.0)),   # holeshot gate before the start/finish
        (2.0, GateCrossing(1, 1, 2.0)),   # S/F: lap 1 starts
        (5.0, GateCrossing(1, 2, 5.0)),
        (8.0, GateCrossing(1, 3, 8.0)),
        (12.0, GateCrossing(2, 1, 12.0)),  # lap 2 starts
        (15.5, GateCrossing(2, 2, 15.5)),
        (21.0, GateCrossing(2, 4, 21.0, finished=True)),
    ]
    laps = [lap for t, c in events if (lap := timer.crossing(t, c))]
    assert [(lap.t_start, lap.t_end) for lap in laps] == [(2.0, 12.0), (12.0, 21.0)]
    assert laps[0].splits == [3.0, 6.0]
    assert laps[1].splits == [3.5]
    assert timer.lap_start is None


def test_native_timing_takes_over_from_the_virtual_gate():
    timer = LapTimer(GATE)
    timer.sample(0.0, (0, 0, -1))
    timer.sample(0.1, (0, 0, 1))  # virtual gate starts a lap...
    assert timer.lap_start is not None
    timer.crossing(0.5, GateCrossing(1, 3, 0.5))  # ...until the sim reports gates
    assert timer.mode == "native" and timer.lap_start is None


def test_find_gate_on_synthetic_flight(flight):
    t, pos, run = flight
    gate = find_gate(t, pos, run)
    assert gate is not None
    laps = lap_times_through(gate, t, pos, run)
    assert len(laps) == 6
    assert max(laps) / min(laps) < 1.15


def test_find_gate_needs_repeated_laps():
    t = np.arange(0, 30, 1 / 60)
    pos = np.column_stack([np.zeros_like(t), np.zeros_like(t), 15.0 * t])  # a straight line
    assert find_gate(t, pos, np.zeros(len(t), int)) is None
