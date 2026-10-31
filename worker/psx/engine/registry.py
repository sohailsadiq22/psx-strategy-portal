"""All 24 strategies with documented rules and default parameters."""
from __future__ import annotations

import copy

import numpy as np

from .base import Context, Signal, StrategyDef, describe, param_hash, GLOBAL_DEFAULTS
from .strategies import candles as cd
from .strategies import chart_patterns as cp
from .strategies import indicator_setups as ind

CANDLE_STOP = "Stop: below pattern low (minus buffer). Target: R-multiple of risk (default 2R)."
CTX = "Context filter: prior downtrend (close < SMA20 and < close 10 bars ago) AND within 3% of the 20-day low or a confirmed support pivot. Optional confirmation: next candle closes above pattern high (default ON)."
CANDLE_INVAL = "Invalidated if the confirmation candle fails to close above the pattern high, or price trades below pattern low."
PAT_STOP_TGT = "Stop below pattern low; target = breakout level + pattern height."

_defs: list[StrategyDef] = []


def _add(number, key, name, tier, category, entry, confirm, exit_, inval, defaults, fn, exit_fn=None):
    def detect(ctx: Context, _fn=fn, _d=defaults):
        p = {**_d, **{k: v for k, v in ctx.params.items() if k in _d}}
        return _fn(ctx, p)

    ex = None
    if exit_fn is not None:
        def ex(ctx: Context, _fn=exit_fn, _d=defaults):
            p = {**_d, **{k: v for k, v in ctx.params.items() if k in _d}}
            return _fn(ctx, p)
    _defs.append(StrategyDef(key, name, number, tier, category, entry, confirm, exit_, inval, defaults, detect, ex))


_add(1, "double_bottom", "Double Bottom", 1, "Chart pattern",
     "Two confirmed pivot lows within 3%, 10-60 bars apart, middle peak >= 8% above the lows; Buy on close above middle peak.",
     "All pivot conditions met and close above the middle peak (volume shown, not required).",
     "Stop below the lower low; target = breakout + 100% of pattern height.",
     "Price closes below the lower low before breakout, or no breakout within 40 bars.",
     {"lows_tolerance_pct": 3.0, "min_bars_between": 10, "max_bars_between": 60, "min_peak_pct": 8.0, "target_pct_of_height": 100.0, "max_bars_to_breakout": 40}, cp.double_bottom)
_add(2, "ascending_triangle", "Ascending Triangle", 1, "Chart pattern",
     "Flat resistance (>= 2 touches within 1%) with >= 2 rising lows, 20-80 bars; Buy on close above resistance.",
     "Close above resistance AND volume >= 1.5x 20-day average.",
     "Stop below last rising low; target = resistance + triangle height.",
     "A new low below the last rising low before breakout.",
     {"resistance_tolerance_pct": 1.0, "min_bars": 20, "max_bars": 80}, cp.ascending_triangle)
_add(3, "bull_flag", "Bull Flag", 1, "Chart pattern",
     "Pole >= 15% within <= 15 bars, flag 5-15 bars retracing <= 50% of pole; Buy on close above flag high.",
     "Volume declining in the flag AND close above flag high.",
     "Stop below flag low; target = flag high + pole height.",
     "Flag retraces more than 50% of the pole or lasts more than 15 bars.",
     {"min_pole_gain_pct": 15.0, "max_pole_bars": 15, "min_flag_bars": 5, "max_flag_bars": 15, "max_retrace_pct": 50.0}, cp.bull_flag)
_add(4, "cup_handle", "Cup & Handle", 1, "Chart pattern",
     "Cup 15-35% deep, 30-120 bars, rims within 5%; handle 5-20 bars retracing <= 50% of depth; Buy on close above handle high.",
     "Close above handle high AND volume >= 1.5x average.",
     "Stop below handle low; target = breakout + cup depth.",
     "Handle retraces more than 50% of cup depth.",
     {"min_depth_pct": 15.0, "max_depth_pct": 35.0, "min_cup_bars": 30, "max_cup_bars": 120, "rim_tolerance_pct": 5.0, "min_handle_bars": 5, "max_handle_bars": 20, "max_handle_retrace_pct": 50.0}, cp.cup_handle)
_add(5, "bullish_engulfing", "Bullish Engulfing", 1, "Candlestick", "Bullish body fully engulfs the previous bearish body.", CTX, CANDLE_STOP, CANDLE_INVAL, {}, cd.bullish_engulfing)
_add(6, "hammer", "Hammer", 1, "Candlestick", "Lower shadow >= 2x body, upper shadow <= 10% of range, body in top third.", CTX, CANDLE_STOP, CANDLE_INVAL,
     {"min_lower_shadow_x_body": 2.0, "max_upper_shadow_pct": 10.0}, cd.hammer)
_add(7, "morning_star", "Morning Star", 1, "Candlestick", "Large bearish candle, small-body candle, bullish candle closing above the first candle's midpoint.", CTX, CANDLE_STOP, CANDLE_INVAL,
     {"large_body_x_avg": 1.0, "small_body_x_first": 0.3}, cd.morning_star)
_add(8, "piercing_line", "Piercing Line", 1, "Candlestick", "Bullish candle opens below prior low (or close) and closes above the prior bearish body midpoint but below its open.", CTX, CANDLE_STOP, CANDLE_INVAL,
     {"open_below": "prior_low"}, cd.piercing_line)
_add(9, "fibonacci", "Fibonacci Retracement", 1, "Indicator setup",
     "Swing leg >= 15% from confirmed pivots; price retraces into the 50%-61.8% zone.",
     "Mandatory: a bullish candle closes above the previous bar's high while in the zone. Fibonacci alone is never a signal.",
     "Stop below the 78.6% level; target = previous swing high.",
     "Price trades below the 78.6% level, or above the swing high before the signal.",
     {"min_leg_pct": 15.0, "zone_top": 0.5, "zone_bottom": 0.618, "invalidation_level": 0.786, "max_leg_bars": 120, "max_leg_age_bars": 60}, ind.fibonacci)
_add(10, "supertrend_ma200", "Supertrend + MA200", 1, "Indicator setup",
     "Supertrend(10,3) flips up AND close > SMA200 AND SMA200 rising.", "All three conditions on the same bar.",
     "Exit when Supertrend flips down. Initial stop at the Supertrend line.", "Close back below the Supertrend line.",
     {"sma_slope_bars": 10, "stop_at_supertrend": True}, ind.supertrend_ma200, ind.supertrend_exit)
_add(11, "donchian", "Donchian Breakout", 1, "Indicator setup",
     "Close above the previous 20-day high (current bar excluded).", "Close-based breakout only.",
     "Exit on close below previous 10-day low. Initial stop = entry - 2x ATR(14).", "Initial stop hit.",
     {"entry_bars": 20, "exit_bars": 10, "stop_atr_mult": 2.0}, ind.donchian, ind.donchian_exit)
_add(12, "rsi_macd", "RSI + MACD", 1, "Indicator setup",
     "RSI(14) crosses above 50 and MACD crosses above signal within 3 bars of each other.", "MACD histogram > 0 AND close > SMA50.",
     "Exit when MACD crosses below signal or RSI < 40. Initial stop = entry - 2x ATR(14).", "Initial stop hit.",
     {"max_bars_apart": 3, "exit_rsi_below": 40.0, "stop_atr_mult": 2.0}, ind.rsi_macd, ind.rsi_macd_exit)
_add(13, "triple_bottom", "Triple Bottom", 2, "Chart pattern", "Three confirmed pivot lows within 3%; Buy on close above the highest peak between them.",
     "Close above resistance (volume shown).", PAT_STOP_TGT, "Close below the lowest low before breakout.",
     {"lows_tolerance_pct": 3.0, "min_bars_between": 5, "max_bars": 120, "min_peak_pct": 5.0, "target_pct_of_height": 100.0, "max_bars_to_breakout": 40}, cp.triple_bottom)
_add(14, "rounding_bottom", "Rounding Bottom", 2, "Chart pattern", "U-shaped base of >= 40 bars (quadratic fit, R^2 >= 0.8, positive curvature, depth 10-35%); Buy on close above the left rim.",
     "Curve-fit quality and close above rim.", "Stop below the most recent confirmed pivot low; target = rim + depth.", "Fit quality fails or price exceeds rim earlier.",
     {"min_bars": 40, "max_bars": 200, "min_r2": 0.8, "vertex_band": 0.5, "min_depth_pct": 10.0, "max_depth_pct": 35.0}, cp.rounding_bottom)
_add(15, "inverse_hs", "Inverse Head & Shoulders", 2, "Chart pattern", "Head lower than both shoulders (>= 3%), shoulders within 5%; Buy on close above the neckline.",
     "Close above neckline AND volume >= 1.5x average.", "Stop below right shoulder; target = neckline + head depth.", "Price breaks below the right shoulder.",
     {"shoulder_tolerance_pct": 5.0, "min_head_depth_pct": 3.0, "min_bars": 15, "max_bars": 150, "max_bars_to_breakout": 40}, cp.inverse_hs)
_add(16, "rectangle", "Rectangle Breakout (Darvas Box)", 2, "Chart pattern", ">= 2 touches on top and bottom within a <= 5% range; Buy on close above the top.",
     "Close above top AND volume >= 1.5x average.", "Stop below box bottom; target = top + box height.", "Close below box bottom.",
     {"max_range_pct": 5.0, "touch_tolerance_pct": 1.0, "windows": [20, 30, 40, 60], "min_bars": 10}, cp.rectangle)
_add(17, "falling_wedge", "Falling Wedge", 2, "Chart pattern", "Least-squares trendlines through >= 2 pivot highs and lows, both falling and converging, 20-100 bars; Buy on close above upper line.",
     "Close above upper trendline.", "Stop below last pivot low; target = wedge start high.", "Close below the lower trendline.",
     {"min_bars": 20, "max_bars": 100, "max_pivots": 4}, cp.falling_wedge)
_add(18, "bullish_harami", "Bullish Harami", 2, "Candlestick", "Small bullish body inside the prior large bearish body.", CTX, CANDLE_STOP, CANDLE_INVAL,
     {"large_body_x_avg": 1.0, "max_body_x_prior": 0.5}, cd.bullish_harami)
_add(19, "three_white_soldiers", "Three White Soldiers", 2, "Candlestick", "Three consecutive bullish candles, each closing higher and opening within the prior body.", CTX, CANDLE_STOP, CANDLE_INVAL, {}, cd.three_white_soldiers)
_add(20, "tweezer_bottom", "Tweezer Bottom", 2, "Candlestick", "Two candles with lows within 0.3%, first bearish, second bullish.", CTX, CANDLE_STOP, CANDLE_INVAL,
     {"low_tolerance_pct": 0.3}, cd.tweezer_bottom)
_add(21, "golden_cross", "Golden Cross", 2, "Indicator setup", "SMA50 crosses above SMA200.", "Cross on close.", "Exit on reverse cross. Optional ATR stop (default off).", "Reverse cross.",
     {"stop_atr_mult": 0.0}, ind.golden_cross, ind.golden_cross_exit)
_add(22, "bollinger_squeeze", "Bollinger Squeeze Breakout", 2, "Indicator setup", "Bandwidth in lowest 20% of last 120 bars, then close above the upper band.",
     "Volume >= 1.5x average.", "Exit on close below middle band. Initial stop = entry - 2x ATR.", "Close back below middle band.",
     {"rank_bars": 120, "squeeze_pct": 20.0, "squeeze_recent_bars": 5, "stop_atr_mult": 2.0}, ind.bollinger_squeeze, ind.bollinger_exit)
_add(23, "high_52w", "52-Week High Breakout", 2, "Indicator setup", "Close above the previous 252-bar high.", "Volume >= 1.5x average.",
     "Exit on close below SMA50. Initial stop = entry - 2x ATR.", "Close back below SMA50.", {"lookback_bars": 252, "stop_atr_mult": 2.0}, ind.high_52w, ind.high_52w_exit)
_add(24, "nr7_inside", "NR7 / Inside Bar Breakout", 2, "Indicator setup", "Narrowest range of last 7 bars (or inside bar); Buy on close above its high within 5 bars.",
     "Close above setup bar high before a low below it.", "Stop below setup bar low; target 2R.", "Price trades below setup bar low first.",
     {"mode": "either", "max_bars_to_breakout": 5, "target_r": 2.0}, ind.nr7_inside)

STRATEGIES: dict[str, StrategyDef] = {s.key: s for s in sorted(_defs, key=lambda s: s.number)}
assert len(STRATEGIES) == 24


def default_params(key: str) -> dict:
    return copy.deepcopy({**GLOBAL_DEFAULTS, **STRATEGIES[key].defaults})


def run_strategy(key: str, ctx: Context) -> tuple[list[Signal], np.ndarray | None]:
    s = STRATEGIES[key]
    sigs = s.detect(ctx)
    for g in sigs:
        g.strategy = key
        if not g.indicators:
            i = g.idx
            g.indicators = {k: (round(float(ctx.df[k].iloc[i]), 4) if np.isfinite(ctx.df[k].iloc[i]) else None)
                            for k in ("sma20", "sma50", "sma200", "rsi14", "atr14", "vol_avg20")}
        g.reason = describe(g, s.name)
    ex = s.exit_signal(ctx) if s.exit_signal else None
    return sigs, ex


__all__ = ["STRATEGIES", "default_params", "run_strategy", "param_hash"]
