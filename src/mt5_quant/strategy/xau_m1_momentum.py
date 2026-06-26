"""XAUUSD M1 三重滤网动量策略（兼容原有 Signal/Position 接口）。

三重过滤：
  1. 价格结构 — 分形识别 Swing High/Low，价格位于趋势通道内
  2. RSI(14) — 50–70（多）/ 30–50（空），且无背离
  3. MACD — 柱状图连续 2 根同向放大

前置检查：ATR < atr_min_threshold 或美盘开盘时段（可配置）→ HOLD
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from mt5_quant.config import StrategyConfig
from mt5_quant.models import Position, Signal
from mt5_quant.strategy.base import Strategy

LOGGER = logging.getLogger(__name__)


# ── 工具函数 ──────────────────────────────────────────────────────────────

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


def _macd(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """返回 (macd_line, signal_line, histogram)。"""
    ema12 = _ema(series, 12)
    ema26 = _ema(series, 26)
    macd_line = ema12 - ema26
    signal_line = _ema(macd_line, 9)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _fractal_top(high: pd.Series, length: int = 2) -> pd.Series:
    """分形高点：当前 high 是左右各 length 根中的最高值。"""
    rolling = high.rolling(window=length * 2 + 1, center=True, min_periods=1)
    return (high == rolling.max()).astype(int)


def _fractal_bottom(low: pd.Series, length: int = 2) -> pd.Series:
    """分形低点：当前 low 是左右各 length 根中的最低值。"""
    rolling = low.rolling(window=length * 2 + 1, center=True, min_periods=1)
    return (low == rolling.min()).astype(int)


def _swing_highs(high: pd.Series, low: pd.Series, length: int = 2) -> pd.Series:
    """最近 3 个分形高点序列（仅保留值）。"""
    fractal = _fractal_top(high, length)
    return high.where(fractal.eq(1)).dropna().tail(3)


def _swing_lows(high: pd.Series, low: pd.Series, length: int = 2) -> pd.Series:
    """最近 3 个分形低点序列（仅保留值）。"""
    fractal = _fractal_bottom(low, length)
    return low.where(fractal.eq(1)).dropna().tail(3)


def _rsi_divergence(
    rsi: pd.Series,
    swing_highs: pd.Series,
    swing_lows: pd.Series,
) -> tuple[bool, bool]:
    """检测 RSI 背离。返回 (bearish_divergence, bullish_divergence)。"""
    bearish = False
    bullish = False
    if len(swing_highs) >= 2:
        price_highs = swing_highs.index
        rsi_at_highs = rsi.loc[price_highs]
        if len(rsi_at_highs.dropna()) >= 2:
            sh = swing_highs.values[-2:]
            rh = rsi_at_highs.values[-2:]
            if len(sh) == 2 and len(rh) == 2:
                if sh[1] > sh[0] and rh[1] < rh[0]:
                    bearish = True
    if len(swing_lows) >= 2:
        price_lows = swing_lows.index
        rsi_at_lows = rsi.loc[price_lows]
        if len(rsi_at_lows.dropna()) >= 2:
            sl = swing_lows.values[-2:]
            rl = rsi_at_lows.values[-2:]
            if len(sl) == 2 and len(rl) == 2:
                if sl[1] < sl[0] and rl[1] > rl[0]:
                    bullish = True
    return bearish, bullish


class XauM1MomentumStrategy(Strategy):
    """适配黄金 M1 三重滤网动量策略。

    保留原策略所有能力，并叠加三重过滤：
      1. 价格结构 — 分形 Swing + 趋势通道
      2. RSI 背离检测
      3. MACD 连续同向放大
      前置 ATR 低波动过滤 + 美盘开盘避险（可配置）
    """

    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

        # ── 三重滤网参数（带默认值，兼容旧配置） ──
        self.atr_min_threshold: float = (
            getattr(config, "atr_min_threshold", None) or 6.0
        )
        self.us_session_blackout: bool = getattr(config, "us_session_blackout", True)
        self.fractal_length: int = getattr(config, "fractal_length", None) or 2
        self.breakout_atr_multiple: float = (
            getattr(config, "breakout_atr_multiple", None) or 1.0
        )

        # ── 原有参数（保持兼容） ──
        self.ema_fast = config.ema_fast
        self.ema_slow = config.ema_slow
        self.rsi_period = config.rsi_period
        self.rsi_buy_threshold = config.rsi_buy_threshold
        self.rsi_sell_threshold = config.rsi_sell_threshold
        self.breakout_lookback = config.breakout_lookback
        self.stop_loss_pct = config.stop_loss_pct
        self.take_profit_pct = config.take_profit_pct
        self.volume_window = config.volume_window
        self.volume_multiplier = config.volume_multiplier
        self.breakout_buffer_pct = config.breakout_buffer_pct

    def generate_signal(self, data: pd.DataFrame, position: Position | None) -> Signal:
        """根据三重滤网共同决定开平仓。"""
        # ── 最小数据长度检查 ──
        min_bars = max(
            self.ema_slow + 3,
            self.rsi_period + 3,
            self.breakout_lookback + 3,
            self.volume_window + 3 if "volume" in data.columns else 0,
            30,
        )
        if len(data) < min_bars:
            return Signal(action="hold", reason="insufficient_bars")

        frame = data.copy()
        frame["ema_fast"] = _ema(frame["close"], self.ema_fast)
        frame["ema_slow"] = _ema(frame["close"], self.ema_slow)
        frame["rsi"] = _rsi(frame["close"], self.rsi_period)
        frame["breakout_high"] = (
            frame["high"].shift(1).rolling(self.breakout_lookback).max()
        )
        frame["breakout_low"] = (
            frame["low"].shift(1).rolling(self.breakout_lookback).min()
        )
        if "volume" in frame.columns:
            frame["volume_mean"] = (
                frame["volume"].shift(1).rolling(self.volume_window).mean()
            )

        # ATR
        atr_period = self.config.atr_period or 14
        frame["atr"] = _atr(frame["high"], frame["low"], frame["close"], atr_period)

        # MACD
        frame["macd"], frame["macd_signal"], frame["macd_hist"] = _macd(
            frame["close"]
        )

        current = frame.iloc[-1]
        previous = frame.iloc[-2]

        if (
            pd.isna(current["ema_fast"])
            or pd.isna(current["ema_slow"])
            or pd.isna(current["rsi"])
            or pd.isna(current["atr"])
        ):
            return Signal(action="hold", reason="indicator_not_ready")

        # ── 前置过滤 1：ATR 低波动 ──
        current_atr = float(current["atr"])
        if current_atr < self.atr_min_threshold:
            return Signal(
                action="hold",
                reason=f"atr_too_low_{current_atr:.1f}",
            )

        # ── 前置过滤 2：美盘开盘避险 ──
        if self.us_session_blackout:
            now_utc = datetime.now(timezone.utc)
            us_open_start = 12 * 60  # 12:00 UTC
            us_open_end = 12 * 60 + 30  # 12:30 UTC
            current_minutes = now_utc.hour * 60 + now_utc.minute
            if us_open_start <= current_minutes < us_open_end:
                return Signal(action="hold", reason="us_session_blackout")

        # ── 原有趋势判断 ──
        uptrend = (
            current["ema_fast"] > current["ema_slow"]
            and current["close"] > current["ema_fast"]
        )
        downtrend = (
            current["ema_fast"] < current["ema_slow"]
            and current["close"] < current["ema_fast"]
        )

        # ── 原有突破判断 ──
        entry = float(current["close"])
        buffer = entry * self.breakout_buffer_pct
        long_breakout = (
            current["close"]
            > current["breakout_high"] + buffer
            and previous["close"] <= previous["breakout_high"]
        )
        short_breakout = (
            current["close"]
            < current["breakout_low"] - buffer
            and previous["close"] >= previous["breakout_low"]
        )

        # ── 三重过滤 1：价格结构 — 分形趋势通道 ──
        fractal_top = _fractal_top(frame["high"], self.fractal_length)
        fractal_bottom = _fractal_bottom(frame["low"], self.fractal_length)

        recent_highs = frame["high"].where(fractal_top.eq(1)).dropna().tail(2)
        recent_lows = frame["low"].where(fractal_bottom.eq(1)).dropna().tail(2)

        price_in_channel = True
        if uptrend and len(recent_lows) >= 1:
            price_in_channel = float(current["low"]) >= float(recent_lows.iloc[-1])
        elif downtrend and len(recent_highs) >= 1:
            price_in_channel = float(current["high"]) <= float(recent_highs.iloc[-1])

        # ── 三重过滤 2：RSI 背离检测 ──
        sh = _swing_highs(frame["high"], frame["low"], self.fractal_length)
        sl = _swing_lows(frame["high"], frame["low"], self.fractal_length)
        bearish_div, bullish_div = _rsi_divergence(frame["rsi"], sh, sl)

        long_momentum = current["rsi"] >= self.rsi_buy_threshold
        short_momentum = current["rsi"] <= self.rsi_sell_threshold

        # ── 三重过滤 3：MACD 柱状图连续同向放大 ──
        if len(frame) >= 3:
            hist_current = float(current["macd_hist"])
            hist_previous = float(previous["macd_hist"])
            hist_before = float(frame.iloc[-3]["macd_hist"])
            macd_bullish = (
                hist_current > hist_previous > hist_before and hist_current > 0
            )
            macd_bearish = (
                hist_current < hist_previous < hist_before and hist_current < 0
            )
        else:
            macd_bullish = False
            macd_bearish = False

        # ── 成交量确认（保留原有逻辑） ──
        volume_confirm = True
        if "volume_mean" in frame.columns and not pd.isna(current["volume_mean"]):
            vol_mean_val = float(current["volume_mean"])
            if vol_mean_val > 0:
                volume_confirm = (
                    float(current["volume"]) >= vol_mean_val * self.volume_multiplier
                )

        # ── 开仓信号（全部通过） ──
        if (
            position is None
            and uptrend
            and long_breakout
            and long_momentum
            and volume_confirm
            and price_in_channel
            and not bearish_div
            and macd_bullish
        ):
            return Signal(
                action="buy",
                stop_loss=entry * (1 - self.stop_loss_pct),
                take_profit=entry * (1 + self.take_profit_pct),
                reason="triple_filter_long",
            )

        if (
            position is None
            and downtrend
            and short_breakout
            and short_momentum
            and volume_confirm
            and price_in_channel
            and not bullish_div
            and macd_bearish
        ):
            return Signal(
                action="sell",
                stop_loss=entry * (1 + self.stop_loss_pct),
                take_profit=entry * (1 - self.take_profit_pct),
                reason="triple_filter_short",
            )

        # ── 持仓管理（保留原有逻辑） ──
        if position is not None:
            if position.side == "buy" and (
                current["ema_fast"] < current["ema_slow"] or current["rsi"] < 48
            ):
                return Signal(action="close", reason="long_momentum_lost")
            if position.side == "sell" and (
                current["ema_fast"] > current["ema_slow"] or current["rsi"] > 52
            ):
                return Signal(action="close", reason="short_momentum_lost")

        return Signal(action="hold", reason="no_signal")
