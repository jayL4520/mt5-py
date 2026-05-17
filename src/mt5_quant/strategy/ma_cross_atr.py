"""通用双均线 ATR 策略。"""

from __future__ import annotations

import pandas as pd

from mt5_quant.config import StrategyConfig
from mt5_quant.models import Position, Signal
from mt5_quant.strategy.base import Strategy


def _atr(data: pd.DataFrame, period: int) -> pd.Series:
    """计算 ATR 指标。"""
    high_low = data["high"] - data["low"]
    high_close = (data["high"] - data["close"].shift(1)).abs()
    low_close = (data["low"] - data["close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(window=period).mean()


class MovingAverageAtrStrategy(Strategy):
    """双均线交叉配合 ATR 止损的基础策略。"""
    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    def generate_signal(self, data: pd.DataFrame, position: Position | None) -> Signal:
        """根据均线交叉和持仓状态生成交易动作。"""
        min_bars = max(self.config.long_window + 2, self.config.atr_period + 2)
        if len(data) < min_bars:
            return Signal(action="hold", reason="insufficient_bars")

        frame = data.copy()
        frame["fast_ma"] = frame["close"].rolling(window=self.config.short_window).mean()
        frame["slow_ma"] = frame["close"].rolling(window=self.config.long_window).mean()
        frame["atr"] = _atr(frame, self.config.atr_period)

        current = frame.iloc[-1]
        previous = frame.iloc[-2]

        if pd.isna(current["fast_ma"]) or pd.isna(current["slow_ma"]) or pd.isna(current["atr"]):
            return Signal(action="hold", reason="indicator_not_ready")

        bull_cross = previous["fast_ma"] <= previous["slow_ma"] and current["fast_ma"] > current["slow_ma"]
        bear_cross = previous["fast_ma"] >= previous["slow_ma"] and current["fast_ma"] < current["slow_ma"]

        entry = float(current["close"])
        atr_value = float(current["atr"])
        stop_distance = atr_value * self.config.atr_stop_multiple

        if bull_cross and position is None:
            stop_loss = entry - stop_distance
            take_profit = entry + (stop_distance * self.config.reward_to_risk)
            return Signal(action="buy", stop_loss=stop_loss, take_profit=take_profit, reason="bull_cross")

        if bear_cross and position is None:
            stop_loss = entry + stop_distance
            take_profit = entry - (stop_distance * self.config.reward_to_risk)
            return Signal(action="sell", stop_loss=stop_loss, take_profit=take_profit, reason="bear_cross")

        if position is not None:
            if position.side == "buy" and bear_cross:
                return Signal(action="close", reason="bear_cross_exit")
            if position.side == "sell" and bull_cross:
                return Signal(action="close", reason="bull_cross_exit")

        return Signal(action="hold", reason="no_signal")
