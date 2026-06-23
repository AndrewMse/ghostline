import numpy as np
import pytest

from ghostline.synthetic import FigureEight, fly_arrays


@pytest.fixture(scope="session")
def track() -> FigureEight:
    return FigureEight()


@pytest.fixture(scope="session")
def flight(track):
    """Six laps of the demo track from a standing start: (t, pos, run)."""
    t, pos = fly_arrays(track, 6, seed=7, mistake_rate=0.0)
    return t, pos, np.zeros(len(t), dtype=int)
