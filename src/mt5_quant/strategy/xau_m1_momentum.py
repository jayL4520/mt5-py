"""XAUUSD M1 趋势突破动量策略。"""

from __future__ import annotations

import pandas as pd

from mt5_quant.config import StrategyConfig
from mt5_quant.models import Position, Signal
from mt5_quant.strategy.base import Strategy


def _ema(series: pd.Series, period: int) -> pd.Series:
    """计算指数移动平均线。"""
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int) -> pd.Series:
    """计算 RSI 动量指标。"""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    return 100 - (100 / (1 + rs))


class XauM1MomentumStrategy(Strategy):
    """适配黄金 1 分钟周期的趋势突破策略。"""
    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    def generate_signal(self, data: pd.DataFrame, position: Position | None) -> Signal:
        """根据趋势、突破和动量共同决定开平仓。"""
        min_bars = max(
            self.config.ema_slow + 3,
            self.config.rsi_period + 3,
            self.config.breakout_lookback + 3,
            self.config.volume_window + 3 if "volume" in data.columns else 0,
        )
        if len(data) < min_bars:
            return Signal(action="hold", reason="insufficient_bars")

        frame = data.copy()
        frame["ema_fast"] = _ema(frame["close"], self.config.ema_fast)
        frame["ema_slow"] = _ema(frame["close"], self.config.ema_slow)
        frame["rsi"] = _rsi(frame["close"], self.config.rsi_period)
        frame["breakout_high"] = frame["high"].shift(1).rolling(self.config.breakout_lookback).max()
        frame["breakout_low"] = frame["low"].shift(1).rolling(self.config.breakout_lookback).min()
        if "volume" in frame.columns:
            frame["volume_mean"] = frame["volume"].shift(1).rolling(self.config.volume_window).mean()

        current = frame.iloc[-1]
        previous = frame.iloc[-2]

        if pd.isna(current["ema_fast"]) or pd.isna(current["ema_slow"]) or pd.isna(current["rsi"]):
            return Signal(action="hold", reason="indicator_not_ready")

        uptrend = current["ema_fast"] > current["ema_slow"] and current["close"] > current["ema_fast"]
        downtrend = current["ema_fast"] < current["ema_slow"] and current["close"] < current["ema_fast"]

        entry = float(current["close"])
        buffer = entry * self.config.breakout_buffer_pct
        long_breakout = current["close"] > current["breakout_high"] + buffer and previous["close"] <= previous["breakout_high"]
        short_breakout = current["close"] < current["breakout_low"] - buffer and previous["close"] >= previous["breakout_low"]

        long_momentum = current["rsi"] >= self.config.rsi_buy_threshold
        short_momentum = current["rsi"] <= self.config.rsi_sell_threshold

        volume_confirm = True
        if "volume_mean" in frame.columns and not pd.isna(current["volume_mean"]) and float(current["volume_mean"]) > 0:
            volume_confirm = float(current["volume"]) >= float(current["volume_mean"]) * self.config.volume_multiplier

        if position is None and uptrend and long_breakout and long_momentum and volume_confirm:
            return Signal(
                action="buy",
                stop_loss=entry * (1 - self.config.stop_loss_pct),
                take_profit=entry * (1 + self.config.take_profit_pct),
                reason="trend_breakout_long",
            )

        if position is None and downtrend and short_breakout and short_momentum and volume_confirm:
            return Signal(
                action="sell",
                stop_loss=entry * (1 + self.config.stop_loss_pct),
                take_profit=entry * (1 - self.config.take_profit_pct),
                reason="trend_breakout_short",
            )

        if position is not None:
            if position.side == "buy" and (current["ema_fast"] < current["ema_slow"] or current["rsi"] < 48):
                return Signal(action="close", reason="long_momentum_lost")
            if position.side == "sell" and (current["ema_fast"] > current["ema_slow"] or current["rsi"] > 52):
                return Signal(action="close", reason="short_momentum_lost")

        return Signal(action="hold", reason="no_signal")
