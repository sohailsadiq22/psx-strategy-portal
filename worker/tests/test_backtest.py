"""Simulator, costs and portfolio rules."""
import numpy as np

from conftest import frame
from psx.backtest.costs import CostModel, cgt_by_tax_year
from psx.backtest.simulator import Rules, Sizing, run_portfolio, simulate_symbol
from psx.engine.base import Check, Context, Signal


def sig(i, stop=None, target=None, stop_atr=None, target_r=None):
    return Signal(i, "Buy", "Test", [Check("ok", True)], stop=stop, target=target, stop_atr=stop_atr, target_r=target_r, strategy="t")


def ctx_from(o, h, l, c):
    return Context(frame(c, open_=o, high=h, low=l))


def test_entry_next_open_not_signal_close():
    c = [100, 101, 102, 103, 104]
    ctx = ctx_from([100, 100.5, 105, 103, 104], [101, 102, 106, 104, 105], [99, 100, 101, 102, 103], c)
    t = simulate_symbol("X", ctx, [sig(1, stop=95, target=200)], None, Rules())[0]
    assert t.entry_idx == 2 and t.entry_raw == 105


def test_same_candle_stop_and_target_assumes_stop_first():
    ctx = ctx_from([100, 100, 100, 100], [101, 101, 115, 101], [99, 99, 90, 99], [100, 100, 100, 100])
    t = simulate_symbol("X", ctx, [sig(1, stop=95, target=110)], None, Rules())[0]
    assert t.exit_raw == 95 and "Stop" in t.exit_reason and "same candle" in t.exit_reason


def test_gap_through_stop_exits_at_open():
    ctx = ctx_from([100, 100, 100, 90, 91], [101, 101, 101, 92, 92], [99, 99, 99, 89, 90], [100, 100, 100, 91, 91])
    t = simulate_symbol("X", ctx, [sig(1, stop=95, target=120)], None, Rules())[0]
    assert t.exit_idx == 3 and t.exit_raw == 90 and "gap" in t.exit_reason


def test_target_hit():
    ctx = ctx_from([100, 100, 100, 104], [101, 101, 103, 111], [99, 99, 99, 103], [100, 100, 102, 110])
    t = simulate_symbol("X", ctx, [sig(1, stop=95, target=110)], None, Rules())[0]
    assert t.exit_raw == 110 and t.exit_reason == "Target Hit"


def test_locked_lower_circuit_exits_next_open():
    c = [100, 100, 100, 92.5, 90]
    ctx = ctx_from([100, 100, 100, 99, 88], [101, 101, 101, 99, 91], [99, 99, 99, 92.5, 87], c)
    t = simulate_symbol("X", ctx, [sig(1, stop=95, target=120)], None, Rules(circuit_pct=7.5))[0]
    assert t.exit_idx == 4 and t.exit_raw == 88 and "LOCKED" in t.exit_reason


def test_one_position_per_symbol():
    n = 30
    ctx = ctx_from([100] * n, [101] * n, [99] * n, [100] * n)
    trades = simulate_symbol("X", ctx, [sig(1, stop=90, target=120), sig(5, stop=90, target=120)], None, Rules())
    assert len(trades) == 1 and trades[0].status == "open"


def test_signal_on_last_bar_is_pending():
    ctx = ctx_from([100] * 5, [101] * 5, [99] * 5, [100] * 5)
    t = simulate_symbol("X", ctx, [sig(4, stop=90)], None, Rules())[0]
    assert t.status == "pending" and t.entry_idx is None


def test_atr_stop_from_actual_entry_and_r_target():
    ctx = ctx_from([100, 100, 104, 104], [101, 101, 105, 105], [99, 99, 103, 103], [100, 100, 104, 104])
    t = simulate_symbol("X", ctx, [sig(1, stop_atr=4, target_r=2)], None, Rules())[0]
    assert t.stop == 100 and t.target == 112


def test_cost_model():
    cm = CostModel()
    side = cm.side_costs(100.0, 1000)
    assert abs(side["brokerage"] - 150.0) < 1e-9
    assert abs(side["sales_tax"] - 19.5) < 1e-9
    low = cm.side_costs(5.0, 1000)
    assert abs(low["brokerage"] - 30.0) < 1e-9, "minimum per-share brokerage applies"
    rt = cm.round_trip(100.0, 110.0, 1000)
    assert abs(rt["gross"] - 10_000) < 1e-9 and rt["net_before_tax"] < rt["gross"]
    assert cm.fill_price(100, "buy") > 100 > cm.fill_price(100, "sell")


def test_cgt_tax_year():
    trades = [{"status": "closed", "exit_date": "2024-06-30", "net_pnl": 1000}, {"status": "closed", "exit_date": "2024-07-01", "net_pnl": 500},
              {"status": "closed", "exit_date": "2024-08-01", "net_pnl": -800}, {"status": "open", "exit_date": None, "net_pnl": 9999}]
    out = cgt_by_tax_year(trades, 15)
    assert out["by_year"]["TY2024"]["cgt"] == 150
    assert out["by_year"]["TY2025"]["cgt"] == 0 and out["by_year"]["TY2025"]["net_gain"] == -300
    assert out["total"] == 150


def test_portfolio_sizing_costs_and_reproducibility():
    n = 20
    ctx = ctx_from([100] * 3 + [110] * (n - 3), [101] * 3 + [121] * (n - 3), [99] * 3 + [109] * (n - 3), [100] * 3 + [120] * (n - 3))
    tr = simulate_symbol("X", ctx, [sig(1, stop=90, target=120)], None, Rules())
    r1 = run_portfolio(tr, 1_000_000, Sizing(mode="pct_equity", pct_equity=10), CostModel())
    r2 = run_portfolio(tr, 1_000_000, Sizing(mode="pct_equity", pct_equity=10), CostModel())
    row = r1["trades"][0]
    assert row["status"] == "closed" and row["shares"] > 0 and row["costs"] > 0
    assert row["entry_price"] * row["shares"] <= 100_000
    assert r1 == r2


def test_insufficient_cash_skips():
    ctx = ctx_from([100] * 6, [101] * 6, [99] * 6, [100] * 6)
    tr = simulate_symbol("X", ctx, [sig(1, stop=90, target=200)], None, Rules())
    r = run_portfolio(tr, 50, Sizing(mode="fixed_amount", fixed_amount=1000), CostModel())
    assert r["trades"][0]["status"] == "skipped"
