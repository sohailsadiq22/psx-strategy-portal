import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def frame(close, open_=None, high=None, low=None, volume=None, start="2020-01-01"):
    c = np.asarray(close, float)
    o = np.asarray(open_ if open_ is not None else np.r_[c[0], c[:-1]], float)
    h = np.asarray(high if high is not None else np.maximum(o, c) * 1.005, float)
    l = np.asarray(low if low is not None else np.minimum(o, c) * 0.995, float)
    v = np.asarray(volume if volume is not None else np.full(len(c), 1e6), float)
    df = pd.DataFrame({"date": pd.bdate_range(start, periods=len(c)), "open": o, "high": h, "low": l, "close": c, "volume": v})
    df["ldcp"] = df["close"].shift(1)
    return df


def random_walk(n=1500, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    o = c * np.exp(rng.normal(0, 0.01, n))
    h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.01, n)))
    l = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.01, n)))
    return frame(c, o, h, l, rng.integers(10_000, 1_000_000, n))


@pytest.fixture(scope="session")
def walk():
    return random_walk()
