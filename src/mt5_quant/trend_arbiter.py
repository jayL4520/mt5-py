"""多周期趋势仲裁器：M1 → M5 → M15 趋势方向协同。

在低周期策略开仓前，调用本模块确认高周期趋势方向，
避免逆大势交易。
"""

from __future__ import annotations

import logging
from typing import Literal

import pandas as pd

LOGGER = logging.getLogger(__name__)

TrendDirection = Literal["bullish", "bearish", "neutral"]


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """计算 ADX 指标。"""
    plus_dm = high.diff()
    minus_dm = low.diff()
    plus_dm[plus_dm < 0] = 0.0
    minus_dm[minus_dm > 0] = 0.0
    # 这里使用简化 ADX 计算，与 ta-lib 逻辑对齐
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    # 方向性指标
    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, pd.NA))
    minus_di = 100 * (abs(minus_dm).ewm(span=period, adjust=False).mean() / atr.replace(0, pd.NA))
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, pd.NA)) * 100
    adx = dx.ewm(span=period, adjust=False).mean()
    return adx


class TrendArbiter:
    """多周期趋势仲裁器。

    根据高周期（M15/M5）的 EMA 多层排列 + ADX 判断全局趋势方向。
    """

    def __init__(self) -> None:
        self.cache: dict[str, dict[str, TrendDirection]] = {}

    def get_global_trend(
        self,
        symbol: str,
        timeframe: str,
        data: pd.DataFrame | None = None,
    ) -> TrendDirection:
        """获取指定品种/周期的全局趋势方向。

        参数:
            symbol: 交易品种
            timeframe: 周期（M15, M5）
            data: 高周期的 OHLC DataFrame（至少 70 根）

        返回:
            "bullish" / "bearish" / "neutral"
        """
        if data is None or len(data) < 70:
            LOGGER.warning(
                "TrendArbiter: 数据不足（%s 根），返回 neutral", len(data) if data is not None else 0
            )
            return "neutral"

        frame = data.copy()
        close = frame["close"]
        high = frame["high"]
        low = frame["low"]

        # 三层 EMA
        ema12 = _ema(close, 12)
        ema30 = _ema(close, 30)
        ema70 = _ema(close, 70)

        current_close = float(close.iloc[-1])
        current_ema12 = float(ema12.iloc[-1])
        current_ema30 = float(ema30.iloc[-1])
        current_ema70 = float(ema70.iloc[-1])

        if pd.isna(current_ema70):
            return "neutral"

        # ADX 确认趋势强度
        adx_period = 14 if timeframe == "M15" else 10
        adx_series = _adx(high, low, close, adx_period)
        current_adx = float(adx_series.iloc[-1]) if not pd.isna(adx_series.iloc[-1]) else 0.0

        # ADX 阈值：M15 > 20, M5 > 25
        adx_threshold = 20 if timeframe == "M15" else 25

        # 多头：EMA12 > EMA30 > EMA70，价格在 EMA70 之上，ADX 足够
        uptrend = (
            current_ema12 > current_ema30 > current_ema70
            and current_close > current_ema70
            and current_adx > adx_threshold
        )

        # 空头：EMA12 < EMA30 < EMA70，价格在 EMA70 之下，ADX 足够
        downtrend = (
            current_ema12 < current_ema30 < current_ema70
            and current_close < current_ema70
            and current_adx > adx_threshold
        )

        direction: TrendDirection = "bullish" if uptrend else ("bearish" if downtrend else "neutral")
        cache_key = f"{symbol}:{timeframe}"
        self.cache[cache_key] = {"direction": direction}
        LOGGER.debug(
            "TrendArbiter[%s] close=%.2f ema12=%.2f ema30=%.2f ema70=%.2f adx=%.2f → %s",
            cache_key,
            current_close,
            current_ema12,
            current_ema30,
            current_ema70,
            current_adx,
            direction,
        )
        return direction
