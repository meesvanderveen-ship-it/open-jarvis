from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)

    ma_up = up.ewm(alpha=1 / period, adjust=False).mean()
    ma_down = down.ewm(alpha=1 / period, adjust=False).mean()

    rs = ma_up / ma_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1)
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(df)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = true_range(df)
    atr_series = tr.ewm(alpha=1 / period, adjust=False).mean()

    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_series.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_series.replace(0, np.nan))

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def bollinger_bands(series: pd.Series, period: int = 20, stddev: float = 2.0):
    mid = series.rolling(period).mean()
    std = series.rolling(period).std(ddof=0)
    upper = mid + stddev * std
    lower = mid - stddev * std
    width_pct = (upper - lower) / mid.replace(0, np.nan)
    return mid, upper, lower, width_pct


def donchian(df: pd.DataFrame, period: int = 20):
    high = df["high"].rolling(period).max()
    low = df["low"].rolling(period).min()
    return high, low


def slope(series: pd.Series, period: int = 10) -> float:
    y = series.tail(period).values
    if len(y) < period:
        return 0.0
    x = np.arange(len(y))
    coef = np.polyfit(x, y, 1)[0]
    return float(coef)
