"""Causal technical indicators. Every value at index i uses only bars <= i."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder ATR."""
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0).where(up.notna())


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(s, fast) - ema(s, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig, line - sig


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(s, n)
    sd = s.rolling(n, min_periods=n).std(ddof=0)
    up, lo = mid + k * sd, mid - k * sd
    return up, mid, lo, (up - lo) / mid


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0):
    """Returns (line, direction) where direction is 1 (up) / -1 (down)."""
    a = atr(df, n).to_numpy()
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    hl2 = (h + l) / 2
    ub, lb = hl2 + mult * a, hl2 - mult * a
    m = len(df)
    fub, flb = np.full(m, np.nan), np.full(m, np.nan)
    line, dirn = np.full(m, np.nan), np.zeros(m)
    for i in range(m):
        if np.isnan(a[i]):
            continue
        if i == 0 or np.isnan(fub[i - 1]):
            fub[i], flb[i], dirn[i] = ub[i], lb[i], 1
            line[i] = flb[i]
            continue
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
        if dirn[i - 1] == -1:
            dirn[i] = 1 if c[i] > fub[i - 1] else -1
        else:
            dirn[i] = -1 if c[i] < flb[i - 1] else 1
        line[i] = flb[i] if dirn[i] == 1 else fub[i]
    return pd.Series(line, index=df.index), pd.Series(dirn, index=df.index)


def rolling_pct_rank(s: pd.Series, n: int) -> pd.Series:
    """Percentile (0..1) of the current value within the trailing n values (inclusive)."""
    return s.rolling(n, min_periods=n).apply(lambda w: (w <= w[-1]).mean(), raw=True)


def add_standard(df: pd.DataFrame) -> pd.DataFrame:
    """Adds commonly used causal indicator columns (in place) and returns df."""
    c = df["close"]
    df["sma20"], df["sma50"], df["sma200"] = sma(c, 20), sma(c, 50), sma(c, 200)
    df["vol_avg20"] = df["volume"].shift(1).rolling(20, min_periods=20).mean()
    df["atr14"] = atr(df, 14)
    df["rsi14"] = rsi(c, 14)
    df["macd"], df["macd_signal"], df["macd_hist"] = macd(c)
    df["bb_up"], df["bb_mid"], df["bb_lo"], df["bb_width"] = bollinger(c)
    df["st_line"], df["st_dir"] = supertrend(df, 10, 3.0)
    df["value_avg20"] = (df["close"] * df["volume"]).shift(1).rolling(20, min_periods=20).mean()
    return df
