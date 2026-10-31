"""Strategy engine: every strategy runs individually, has docs, never uses future bars, and detects hand-built patterns."""
import numpy as np
import pytest

from conftest import frame, random_walk
from psx.engine.base import Context, param_hash
from psx.engine.indicators import add_standard
from psx.engine.pivots import PivotIndex, find_pivots
from psx.engine.registry import STRATEGIES, default_params, run_strategy

KEYS = list(STRATEGIES)


def test_registry_has_24_documented_strategies():
    assert len(STRATEGIES) == 24
    assert sorted(s.number for s in STRATEGIES.values()) == list(range(1, 25))
    for s in STRATEGIES.values():
        d = s.doc()
        for k in ("entry_rule", "confirmation_rule", "exit_rule", "invalidation_rule"):
            assert len(d[k]) > 10, (s.key, k)
        assert default_params(s.key)


@pytest.mark.parametrize("key", KEYS)
def test_strategy_runs_individually_with_valid_signals(key, walk):
    ctx = Context(add_standard(walk.copy()), default_params(key))
    sigs, ex = run_strategy(key, ctx)
    for s in sigs:
        assert s.action in ("Buy", "Watch")
        assert s.checks, "every signal carries a confirmation checklist"
        assert (s.action == "Buy") == s.confirmed or s.action == "Watch"
        assert s.stop is not None or s.stop_atr is not None or STRATEGIES[key].exit_signal is not None
        if s.stop is not None and s.action == "Buy":
            assert s.stop < ctx.h[s.idx]
        assert s.reason
    if ex is not None:
        assert len(ex) == ctx.n


@pytest.mark.parametrize("key", KEYS)
def test_no_lookahead(key):
    """Signals up to bar k must be identical whether or not bars after k exist."""
    full = add_standard(random_walk(900, seed=7))
    ctx_full = Context(full, default_params(key))
    sig_full, _ = run_strategy(key, ctx_full)
    for cut in (500, 700):
        trunc = add_standard(random_walk(900, seed=7).iloc[:cut].copy())
        sig_t, _ = run_strategy(key, Context(trunc, default_params(key)))
        a = {(s.idx, s.action, round(s.stop or 0, 6), round(s.target or 0, 6)) for s in sig_full if s.idx < cut - 1 and s.action == "Buy"}
        b = {(s.idx, s.action, round(s.stop or 0, 6), round(s.target or 0, 6)) for s in sig_t if s.idx < cut - 1 and s.action == "Buy"}
        assert a == b, f"{key}: signals before bar {cut} changed when future bars were added"


def test_indicators_are_causal():
    df = random_walk(400, seed=3)
    a = add_standard(df.copy())
    b = add_standard(df.iloc[:300].copy())
    cols = ["sma20", "sma200", "rsi14", "macd", "atr14", "bb_up", "st_line", "vol_avg20"]
    np.testing.assert_allclose(a[cols].iloc[:300].to_numpy(float), b[cols].to_numpy(float), equal_nan=True)


def test_pivots_confirmed_after_n_bars():
    c = [10, 9, 8, 7, 6, 5, 6, 7, 8, 9, 10, 11, 12]
    df = frame(c, high=np.array(c) + 0.1, low=np.array(c) - 0.1)
    piv = [p for p in find_pivots(df, 5) if p.kind == "L"]
    assert piv and piv[0].idx == 5 and piv[0].confirm_idx == 10
    pi = PivotIndex(piv)
    assert not pi.known_at(9, "L") and pi.known_at(10, "L")


def test_param_hash_stable_and_sensitive():
    p = default_params("donchian")
    assert param_hash(p) == param_hash(dict(reversed(list(p.items()))))
    q = {**p, "entry_bars": p.get("entry_bars", 20) + 1}
    assert param_hash(p) != param_hash(q)


def _trend(n, start, step):
    return start + step * np.arange(n)


def test_double_bottom_positive_and_negative():
    seg = np.r_[_trend(30, 130, -1.0), _trend(10, 100, 1.5), _trend(10, 115, -1.5), _trend(25, 100.5, 1.2)]
    df = frame(seg, high=seg + 0.3, low=seg - 0.3, volume=np.r_[np.full(70, 1e6), np.full(5, 3e6)])
    sigs, _ = run_strategy("double_bottom", Context(add_standard(df), default_params("double_bottom")))
    buys = [s for s in sigs if s.action == "Buy"]
    assert buys, "double bottom should be detected"
    assert buys[0].idx > 55 and buys[0].stop < 100
    flat = frame(_trend(75, 100, 0.5))
    assert not [s for s in run_strategy("double_bottom", Context(add_standard(flat), default_params("double_bottom")))[0] if s.action == "Buy"]


def test_bullish_engulfing_positive_and_negative():
    c = np.r_[_trend(25, 120, -0.8), [100.0]]
    o = np.r_[c[:-1] + 0.6, [99.0]]
    c = np.r_[c[:-1], [101.5]]
    c2, o2 = np.r_[c, [103.0]], np.r_[o, [101.6]]
    df = frame(c2, open_=o2, high=np.maximum(o2, c2) + 0.2, low=np.minimum(o2, c2) - 0.2)
    sigs, _ = run_strategy("bullish_engulfing", Context(add_standard(df), default_params("bullish_engulfing")))
    assert any(s.idx == 26 and s.action == "Buy" for s in sigs), sigs  # confirmed on the next candle
    up = frame(_trend(30, 100, 0.8))
    assert not run_strategy("bullish_engulfing", Context(add_standard(up), default_params("bullish_engulfing")))[0]


def test_donchian_breakout_positive_and_negative():
    base = np.r_[np.full(40, 100.0) + np.sin(np.arange(40)) * 0.5, [103.0]]
    sigs, _ = run_strategy("donchian", Context(add_standard(frame(base)), default_params("donchian")))
    assert any(s.idx == 40 and s.action == "Buy" for s in sigs)
    flat = np.full(41, 100.0) + np.sin(np.arange(41)) * 0.5
    assert not [s for s in run_strategy("donchian", Context(add_standard(frame(flat)), default_params("donchian")))[0] if s.idx == 40]


def test_golden_cross_positive():
    c = np.r_[_trend(220, 150, -0.2), _trend(120, 106, 0.6)]
    sigs, _ = run_strategy("golden_cross", Context(add_standard(frame(c)), default_params("golden_cross")))
    assert [s for s in sigs if s.action == "Buy"]
