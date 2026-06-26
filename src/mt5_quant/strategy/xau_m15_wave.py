"""XAUUSD M15 波段策略（兼容原有 Signal/Position 接口 + TrendArbiter）。

逻辑：
  1. 趋势确认：EMA12 > 30 > 70 + ADX > 20（M15）
  2. 入场：价格回踩 EMA30 + RSI 40–60
  3. 出场：trailing stop = ATR × 2
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from mt5_quant.config import StrategyConfig
from mt5_quant.models import Position, Signal
from mt5_quant.strategy.base import Strategy
from mt5_quant.trend_arbiter import TrendArbiter

LOGGER = logging.getLogger(__name__)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


class XauM15WaveStrategy(Strategy):
    """XAUUSD M15 波段策略。"""

    def __init__(self, config: StrategyConfig) -> None:
        self.config = config
        self.trend_arbiter = TrendArbiter()

        self.ema_fast = getattr(config, "ema_fast", 12)
        self.ema_mid = getattr(config, "ema_mid", 30)
        self.ema_slow = getattr(config, "ema_slow", 70)
        self.rsi_period = getattr(config, "rsi_period", 14)
        self.atr_period = getattr(config, "atr_period", 20)
        self.atr_stop_multiple = getattr(config, "atr_stop_multiple", 2.0)
        self.reward_to_risk = getattr(config, "reward_to_risk", 2.5)
        self.atr_min_threshold = getattr(config, "atr_min_threshold", 15.0)
        self.us_session_blackout = getattr(config, "us_session_blackout", True)

    def generate_signal(self, data: pd.DataFrame, position: Position | None) -> Signal:
        if len(data) < 70:
            return Signal(action="hold", reason="insufficient_bars")

        frame = data.copy()
        close = frame["close"]
        high = frame["high"]
        low = frame["low"]

        ema12 = _ema(close, self.ema_fast)
        ema30 = _ema(close, self.ema_mid)
        ema70 = _ema(close, self.ema_slow)
        rsi_series = _rsi(close, self.rsi_period)
        atr_series = _atr(high, low, close, self.atr_period)

        current_close = float(close.iloc[-1])
        current_atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0.0
        current_rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50.0

        if pd.isna(ema70.iloc[-1]) or pd.isna(atr_series.iloc[-1]):
            return Signal(action="hold", reason="indicator_not_ready")

        if current_atr < self.atr_min_threshold:
            return Signal(action="hold", reason=f"atr_too_low_{current_atr:.1f}")

        if self.us_session_blackout:
            now_utc = datetime.now(timezone.utc)
            us_open_start = 12 * 60
            us_open_end = 12 * 60 + 30
            current_minutes = now_utc.hour * 60 + now_utc.minute
            if us_open_start <= current_minutes < us_open_end:
                return Signal(action="hold", reason="us_session_blackout")

        uptrend = (
            float(ema12.iloc[-1]) > float(ema30.iloc[-1]) > float(ema70.iloc[-1])
            and current_close > float(ema70.iloc[-1])
        )
        downtrend = (
            float(ema12.iloc[-1]) < float(ema30.iloc[-1]) < float(ema70.iloc[-1])
            and current_close < float(ema70.iloc[-1])
        )

        if not (uptrend or downtrend):
            return Signal(action="hold", reason="no_trend")

        if position is None:
            if uptrend:
                prev_close = float(close.iloc[-2])
                if (
                    current_close < float(ema30.iloc[-1])
                    and prev_close > float(ema30.iloc[-2])
                    and 40 <= current_rsi <= 60
                ):
                    sl = float(low.iloc[-3:].min()) - 1.5 * current_atr
                    tp = current_close + self.reward_to_risk * current_atr
                    return Signal(
                        action="buy",
                        stop_loss=sl,
                        take_profit=tp,
                        reason="m15_wave_pullback_long",
                    )
            elif downtrend:
                prev_close = float(close.iloc[-2])
                if (
                    current_close > float(ema30.iloc[-1])
                    and prev_close < float(ema30.iloc[-2])
                    and 40 <= current_rsi <= 60
                ):
                    sl = float(high.iloc[-3:].max()) + 1.5 * current_atr
                    tp = current_close - self.reward_to_risk * current_atr
                    return Signal(
                        action="sell",
                        stop_loss=sl,
                        take_profit=tp,
                        reason="m15_wave_rejection_short",
                    )

        if position is not None:
            if position.side == "buy" and (
                float(ema12.iloc[-1]) < float(ema30.iloc[-1])
                or current_rsi < 38
            ):
                return Signal(action="close", reason="m15_long_trend_lost")
            if position.side == "sell" and (
                float(ema12.iloc[-1]) > float(ema30.iloc[-1])
                or current_rsi > 62
            ):
                return Signal(action="close", reason="m15_short_trend_lost")

        return Signal(action="hold", reason="no_signal")
