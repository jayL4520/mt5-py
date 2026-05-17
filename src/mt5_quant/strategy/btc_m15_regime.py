"""BTCUSD M15 趋势状态突破策略。"""

from __future__ import annotations

import numpy as np
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


def _atr(data: pd.DataFrame, period: int) -> pd.Series:
    """计算 ATR 波动率。"""
    high_low = data["high"] - data["low"]
    high_close = (data["high"] - data["close"].shift(1)).abs()
    low_close = (data["low"] - data["close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _adx(data: pd.DataFrame, period: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """计算 ADX、+DI 和 -DI，用于趋势强度判断。"""
    up_move = data["high"].diff()
    down_move = -data["low"].diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=data.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=data.index,
    )

    atr = _atr(data, period)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr.replace(0.0, pd.NA)
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr.replace(0.0, pd.NA)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, pd.NA)
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return adx, plus_di, minus_di


class BtcM15RegimeStrategy(Strategy):
    """适配 BTCUSD M15 的趋势状态突破策略。"""

    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    def generate_signal(self, data: pd.DataFrame, position: Position | None) -> Signal:
        """综合趋势、波动、突破和成交量判断开平仓。"""
        min_bars = max(
            self.config.ema_slow + 3,
            self.config.rsi_period + 3,
            self.config.adx_period + 3,
            self.config.breakout_lookback + 3,
            self.config.volume_window + 3,
            self.config.atr_period + 3,
        )
        if len(data) < min_bars:
            return Signal(action="hold", reason="insufficient_bars")

        frame = data.copy()
        if "volume" not in frame.columns:
            frame["volume"] = 0.0

        frame["ema_fast"] = _ema(frame["close"], self.config.ema_fast)
        frame["ema_slow"] = _ema(frame["close"], self.config.ema_slow)
        frame["rsi"] = _rsi(frame["close"], self.config.rsi_period)
        frame["atr"] = _atr(frame, self.config.atr_period)
        frame["adx"], frame["plus_di"], frame["minus_di"] = _adx(frame, self.config.adx_period)
        frame["breakout_high"] = frame["high"].shift(1).rolling(self.config.breakout_lookback).max()
        frame["breakout_low"] = frame["low"].shift(1).rolling(self.config.breakout_lookback).min()
        frame["volume_mean"] = frame["volume"].shift(1).rolling(self.config.volume_window).mean()

        current = frame.iloc[-1]
        previous = frame.iloc[-2]

        required = [
            current["ema_fast"],
            current["ema_slow"],
            current["rsi"],
            current["atr"],
            current["adx"],
            current["plus_di"],
            current["minus_di"],
            current["breakout_high"],
            current["breakout_low"],
        ]
        if any(pd.isna(value) for value in required):
            return Signal(action="hold", reason="indicator_not_ready")

        close_price = float(current["close"])
        atr_value = float(current["atr"])
        buffer = close_price * self.config.breakout_buffer_pct
        volume_confirm = True
        if not pd.isna(current["volume_mean"]) and float(current["volume_mean"]) > 0:
            volume_confirm = float(current["volume"]) >= float(current["volume_mean"]) * self.config.volume_multiplier

        long_regime = (
            current["ema_fast"] > current["ema_slow"]
            and current["adx"] >= self.config.adx_threshold
            and current["plus_di"] > current["minus_di"]
            and current["rsi"] >= self.config.rsi_buy_threshold
        )
        short_regime = (
            current["ema_fast"] < current["ema_slow"]
            and current["adx"] >= self.config.adx_threshold
            and current["minus_di"] > current["plus_di"]
            and current["rsi"] <= self.config.rsi_sell_threshold
        )

        long_breakout = close_price > float(current["breakout_high"]) + buffer and previous["close"] <= previous["breakout_high"]
        short_breakout = close_price < float(current["breakout_low"]) - buffer and previous["close"] >= previous["breakout_low"]

        stop_distance = atr_value * self.config.atr_stop_multiple
        if stop_distance <= 0:
            return Signal(action="hold", reason="invalid_stop_distance")

        if position is None and long_regime and long_breakout and volume_confirm:
            return Signal(
                action="buy",
                stop_loss=close_price - stop_distance,
                take_profit=close_price + stop_distance * self.config.reward_to_risk,
                reason="btc_regime_breakout_long",
            )

        if position is None and short_regime and short_breakout and volume_confirm:
            return Signal(
                action="sell",
                stop_loss=close_price + stop_distance,
                take_profit=close_price - stop_distance * self.config.reward_to_risk,
                reason="btc_regime_breakout_short",
            )

        if position is not None:
            if position.side == "buy":
                if current["ema_fast"] < current["ema_slow"] or current["plus_di"] < current["minus_di"] or current["adx"] < self.config.adx_threshold * 0.8:
                    return Signal(action="close", reason="btc_long_regime_lost")
            if position.side == "sell":
                if current["ema_fast"] > current["ema_slow"] or current["minus_di"] < current["plus_di"] or current["adx"] < self.config.adx_threshold * 0.8:
                    return Signal(action="close", reason="btc_short_regime_lost")

        return Signal(action="hold", reason="no_signal")
