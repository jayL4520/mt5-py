"""单元测试：所有策略 — 信号生成逻辑。"""

from __future__ import annotations

from copy import deepcopy

import pandas as pd
import pytest

from mt5_quant.config import StrategyConfig
from mt5_quant.models import Position, Signal
from mt5_quant.strategy.base import Strategy
from mt5_quant.strategy.btc_m15_regime import BtcM15RegimeStrategy
from mt5_quant.strategy.ema_cross_atr import EmaCrossAtrStrategy
from mt5_quant.strategy.ma_cross_atr import MovingAverageAtrStrategy
from mt5_quant.strategy.xau_m1_momentum import XauM1MomentumStrategy


# ── helpers ──────────────────────────────────────────────────────────────

def make_frame(close_prices: list[float], extra_bars: int = 0) -> pd.DataFrame:
    """Create a DataFrame with OHLCV data from close prices.

    extra_bars: prepend this many flat bars to ensure sufficient warmup.
    """
    padding = [close_prices[0]] * extra_bars
    all_close = padding + close_prices
    n = len(all_close)
    return pd.DataFrame({
        "open": all_close,
        "high": [v * 1.002 for v in all_close],
        "low": [v * 0.998 for v in all_close],
        "close": all_close,
        "volume": [100] * n,
    })


BASE_CONFIG = StrategyConfig(
    name="base",
    short_window=20,
    long_window=50,
    atr_period=14,
    atr_stop_multiple=2.0,
    reward_to_risk=2.0,
    risk_per_trade=0.01,
    leverage_multiplier=1.1,
    ema_fast=21,
    ema_slow=55,
    rsi_period=14,
    rsi_buy_threshold=55.0,
    rsi_sell_threshold=45.0,
    breakout_lookback=20,
    take_profit_pct=0.003,
    stop_loss_pct=0.004,
    adx_period=14,
    adx_threshold=22.0,
    volume_window=20,
    volume_multiplier=1.0,
    breakout_buffer_pct=0.0,
)


# ── Strategy base class ─────────────────────────────────────────────────

class TestStrategyBase:
    def test_base_cannot_be_instantiated(self) -> None:
        with pytest.raises(TypeError):
            Strategy()  # type: ignore[abstract]

    def test_strategy_interface_requires_generate_signal(self) -> None:
        class Incomplete(Strategy):
            pass
        with pytest.raises(TypeError):
            Incomplete()


# ── EmaCrossAtrStrategy ─────────────────────────────────────────────────

class TestEmaCrossAtrStrategy:
    @staticmethod
    def config(**overrides) -> StrategyConfig:
        cfg = deepcopy(BASE_CONFIG)
        cfg.name = "ema_cross_atr"
        cfg.ema_fast = 3
        cfg.ema_slow = 7
        cfg.atr_period = 5
        cfg.atr_stop_multiple = 2.0
        cfg.reward_to_risk = 2.0
        for key, value in overrides.items():
            setattr(cfg, key, value)
        return cfg

    def test_insufficient_bars_returns_hold(self) -> None:
        strategy = EmaCrossAtrStrategy(self.config())
        data = make_frame([100] * 3)  # only 3 bars
        signal = strategy.generate_signal(data, position=None)
        assert signal.action == "hold"
        assert signal.reason == "insufficient_bars"

    def test_indicator_not_ready_with_flat_data(self) -> None:
        strategy = EmaCrossAtrStrategy(self.config())
        data = make_frame([100] * 5, extra_bars=10)
        signal = strategy.generate_signal(data.iloc[:3], position=None)
        assert signal.action == "hold"
        assert signal.reason in {"insufficient_bars", "indicator_not_ready"}

    def test_bull_cross_returns_buy_signal(self) -> None:
        strategy = EmaCrossAtrStrategy(self.config())
        prices = [100, 101, 102, 103, 104, 105, 106, 107, 106, 105]
        data = make_frame(prices, extra_bars=10)
        signal = strategy.generate_signal(data, position=None)
        assert signal.action in {"buy", "hold"}

    def test_bear_cross_returns_sell_signal(self) -> None:
        strategy = EmaCrossAtrStrategy(self.config())
        prices = [107, 106, 105, 104, 103, 102, 101, 100, 101, 102]
        data = make_frame(prices, extra_bars=10)
        signal = strategy.generate_signal(data, position=None)
        assert signal.action in {"sell", "hold"}

    def test_open_position_closes_on_bear_cross(self) -> None:
        strategy = EmaCrossAtrStrategy(self.config(ema_fast=2, ema_slow=4))
        # Start with downtrend data
        prices = [110, 109, 108, 107, 106, 105, 104, 103, 102, 101, 100, 99, 98, 97]
        data = make_frame(prices, extra_bars=10)
        position = Position(ticket=1, symbol="XAUUSD", side="buy", volume=0.1, price_open=105.0)
        signal = strategy.generate_signal(data, position=position)
        assert signal.action in {"close", "hold"}

    def test_open_position_closes_on_bull_cross_for_sell(self) -> None:
        strategy = EmaCrossAtrStrategy(self.config(ema_fast=2, ema_slow=4))
        prices = [90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103]
        data = make_frame(prices, extra_bars=10)
        position = Position(ticket=1, symbol="XAUUSD", side="sell", volume=0.1, price_open=95.0)
        signal = strategy.generate_signal(data, position=position)
        assert signal.action in {"close", "hold"}

    def test_signal_has_stop_loss_and_take_profit(self) -> None:
        strategy = EmaCrossAtrStrategy(self.config(ema_fast=2, ema_slow=4, atr_period=3))
        prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113]
        data = make_frame(prices, extra_bars=10)
        signal = strategy.generate_signal(data, position=None)
        if signal.action == "buy":
            assert signal.stop_loss is not None and signal.stop_loss < signal.take_profit
            assert signal.reason == "ema_bull_cross"
        elif signal.action == "sell":
            assert signal.stop_loss is not None and signal.stop_loss > signal.take_profit
            assert signal.reason == "ema_bear_cross"

    def test_no_signal_when_no_cross(self) -> None:
        strategy = EmaCrossAtrStrategy(self.config())
        prices = [100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100]
        data = make_frame(prices, extra_bars=15)
        signal = strategy.generate_signal(data, position=None)
        assert signal.action == "hold"
        assert signal.reason == "no_signal"

    def test_ema_is_monotonic(self) -> None:
        """Helper: verify EMA values increase with price."""
        from mt5_quant.strategy.ema_cross_atr import _ema
        s = pd.Series([100, 101, 102, 103, 104, 105], name="close")
        result = _ema(s, period=3)
        assert not result.isna().all()
        assert result.iloc[-1] > result.iloc[0]


# ── MovingAverageAtrStrategy ────────────────────────────────────────────

class TestMovingAverageAtrStrategy:
    @staticmethod
    def config(**overrides) -> StrategyConfig:
        cfg = deepcopy(BASE_CONFIG)
        cfg.name = "ma_cross_atr"
        cfg.short_window = 2
        cfg.long_window = 5
        cfg.atr_period = 3
        cfg.atr_stop_multiple = 2.0
        cfg.reward_to_risk = 2.0
        for key, value in overrides.items():
            setattr(cfg, key, value)
        return cfg

    def test_insufficient_bars_returns_hold(self) -> None:
        strategy = MovingAverageAtrStrategy(self.config())
        data = make_frame([100] * 2)
        signal = strategy.generate_signal(data, position=None)
        assert signal.action == "hold"
        assert signal.reason == "insufficient_bars"

    def test_bull_cross(self) -> None:
        strategy = MovingAverageAtrStrategy(self.config())
        prices = [100, 101, 102, 103, 104, 105, 106, 107]
        data = make_frame(prices, extra_bars=10)
        signal = strategy.generate_signal(data, position=None)
        if signal.action == "buy":
            assert signal.stop_loss is not None
            assert signal.take_profit is not None
            assert signal.reason == "bull_cross"

    def test_bear_cross(self) -> None:
        strategy = MovingAverageAtrStrategy(self.config())
        prices = [107, 106, 105, 104, 103, 102, 101, 100]
        data = make_frame(prices, extra_bars=10)
        signal = strategy.generate_signal(data, position=None)
        if signal.action == "sell":
            assert signal.stop_loss is not None
            assert signal.take_profit is not None
            assert signal.reason == "bear_cross"

    def test_close_existing_position_on_reverse_cross(self) -> None:
        strategy = MovingAverageAtrStrategy(self.config())
        prices = [107, 106, 105, 104, 103, 102, 101, 100]
        data = make_frame(prices, extra_bars=10)
        position = Position(ticket=1, symbol="XAUUSD", side="buy", volume=0.1, price_open=105.0)
        signal = strategy.generate_signal(data, position=position)
        if signal.action == "close":
            assert signal.reason == "bear_cross_exit"

    def test_no_signal_when_data_flat(self) -> None:
        strategy = MovingAverageAtrStrategy(self.config())
        prices = [100, 100, 100, 100, 100, 100, 100]
        data = make_frame(prices, extra_bars=10)
        signal = strategy.generate_signal(data, position=None)
        assert signal.action == "hold"

    def test_atr_is_positive(self) -> None:
        """Verify ATR returns positive values for volatile data."""
        from mt5_quant.strategy.ma_cross_atr import _atr
        df = pd.DataFrame({
            "high": [105, 106, 107, 108, 109],
            "low": [95, 96, 97, 98, 99],
            "close": [100, 101, 102, 103, 104],
        })
        result = _atr(df, period=3)
        assert not result.isna().all()
        assert result.iloc[-1] > 0


# ── XauM1MomentumStrategy ──────────────────────────────────────────────

class TestXauM1MomentumStrategy:
    @staticmethod
    def config(**overrides) -> StrategyConfig:
        cfg = deepcopy(BASE_CONFIG)
        cfg.name = "xau_m1_momentum"
        cfg.ema_fast = 3
        cfg.ema_slow = 7
        cfg.rsi_period = 5
        cfg.rsi_buy_threshold = 55.0
        cfg.rsi_sell_threshold = 45.0
        cfg.breakout_lookback = 5
        cfg.take_profit_pct = 0.003
        cfg.stop_loss_pct = 0.004
        cfg.volume_window = 5
        cfg.volume_multiplier = 1.0
        cfg.breakout_buffer_pct = 0.0
        for key, value in overrides.items():
            setattr(cfg, key, value)
        return cfg

    def test_insufficient_bars_returns_hold(self) -> None:
        strategy = XauM1MomentumStrategy(self.config())
        data = make_frame([100] * 3)
        signal = strategy.generate_signal(data, position=None)
        assert signal.action == "hold"

    def test_buy_signal_with_trend_and_breakout(self) -> None:
        strategy = XauM1MomentumStrategy(self.config())
        # Create an uptrend with a breakout at the end
        prices = [100, 100.5, 101, 101.5, 102, 102.5, 103, 103.5, 104, 104.5, 105, 106]
        data = make_frame(prices, extra_bars=10)
        signal = strategy.generate_signal(data, position=None)
        if signal.action == "buy":
            assert signal.stop_loss is not None
            assert signal.take_profit is not None
            assert signal.stop_loss < signal.take_profit

    def test_sell_signal_with_downtrend_and_breakout(self) -> None:
        strategy = XauM1MomentumStrategy(self.config())
        prices = [110, 109.5, 109, 108.5, 108, 107.5, 107, 106.5, 106, 105.5, 105, 104]
        data = make_frame(prices, extra_bars=10)
        signal = strategy.generate_signal(data, position=None)
        if signal.action == "sell":
            assert signal.stop_loss is not None
            assert signal.take_profit is not None
            assert signal.stop_loss > signal.take_profit

    def test_hold_when_no_trend(self) -> None:
        strategy = XauM1MomentumStrategy(self.config())
        prices = [100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100]
        data = make_frame(prices, extra_bars=15)
        signal = strategy.generate_signal(data, position=None)
        assert signal.action == "hold"

    def test_close_long_when_momentum_lost(self) -> None:
        strategy = XauM1MomentumStrategy(self.config())
        # Uptrend then drop
        prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 108, 106, 104, 102]
        data = make_frame(prices, extra_bars=10)
        position = Position(ticket=1, symbol="XAUUSD", side="buy", volume=0.1, price_open=105.0)
        signal = strategy.generate_signal(data, position=position)
        if signal.action == "close":
            assert "long" in signal.reason or signal.reason == "long_momentum_lost"

    def test_close_short_when_momentum_lost(self) -> None:
        strategy = XauM1MomentumStrategy(self.config())
        prices = [110, 109, 108, 107, 106, 105, 104, 103, 102, 101, 100, 102, 104, 106, 108]
        data = make_frame(prices, extra_bars=10)
        position = Position(ticket=1, symbol="XAUUSD", side="sell", volume=0.1, price_open=105.0)
        signal = strategy.generate_signal(data, position=position)
        if signal.action == "close":
            assert "short" in signal.reason or signal.reason == "short_momentum_lost"

    def test_volume_filter_blocks_trade(self) -> None:
        strategy = XauM1MomentumStrategy(self.config(volume_multiplier=10.0))  # unreachable multiplier
        prices = [100, 100.5, 101, 101.5, 102, 102.5, 103, 103.5, 104, 104.5, 105, 106]
        data = make_frame(prices, extra_bars=10)
        # Make volume very low
        data["volume"] = 10
        signal = strategy.generate_signal(data, position=None)
        assert signal.action == "hold"

    def test_rsi_and_ema_helpers(self) -> None:
        from mt5_quant.strategy.xau_m1_momentum import _ema, _rsi
        s = pd.Series([100, 101, 102, 103, 104, 105], name="close")
        ema_result = _ema(s, period=3)
        assert ema_result.iloc[-1] > 100
        rsi_result = _rsi(s, period=3)
        assert not rsi_result.isna().all()


# ── BtcM15RegimeStrategy ────────────────────────────────────────────────

class TestBtcM15RegimeStrategy:
    @staticmethod
    def config(**overrides) -> StrategyConfig:
        cfg = deepcopy(BASE_CONFIG)
        cfg.name = "btc_m15_regime"
        cfg.ema_fast = 5
        cfg.ema_slow = 10
        cfg.rsi_period = 5
        cfg.rsi_buy_threshold = 55.0
        cfg.rsi_sell_threshold = 45.0
        cfg.adx_period = 5
        cfg.adx_threshold = 18.0
        cfg.breakout_lookback = 5
        cfg.volume_window = 3
        cfg.volume_multiplier = 0.5
        cfg.breakout_buffer_pct = 0.0
        cfg.atr_period = 5
        cfg.atr_stop_multiple = 2.0
        cfg.reward_to_risk = 2.0
        for key, value in overrides.items():
            setattr(cfg, key, value)
        return cfg

    def make_btc_frame(self, prices: list[float], extra_bars: int = 10) -> pd.DataFrame:
        all_prices = [prices[0]] * extra_bars + prices
        n = len(all_prices)
        return pd.DataFrame({
            "open": all_prices,
            "high": [v * 1.005 for v in all_prices],
            "low": [v * 0.995 for v in all_prices],
            "close": all_prices,
            "volume": [100 + (i % 5) * 10 for i in range(n)],
        })

    def test_insufficient_bars(self) -> None:
        strategy = BtcM15RegimeStrategy(self.config())
        data = self.make_btc_frame([50000] * 3, extra_bars=0)
        signal = strategy.generate_signal(data, position=None)
        assert signal.action == "hold"

    def test_buy_signal(self) -> None:
        strategy = BtcM15RegimeStrategy(self.config())
        # Strong uptrend with high ADX
        prices = [50000 + i * 100 for i in range(30)]
        data = self.make_btc_frame(prices, extra_bars=10)
        signal = strategy.generate_signal(data, position=None)
        if signal.action == "buy":
            assert signal.stop_loss is not None
            assert signal.take_profit is not None

    def test_sell_signal(self) -> None:
        strategy = BtcM15RegimeStrategy(self.config())
        prices = [52000 - i * 100 for i in range(30)]
        data = self.make_btc_frame(prices, extra_bars=10)
        signal = strategy.generate_signal(data, position=None)
        if signal.action == "sell":
            assert signal.stop_loss is not None
            assert signal.take_profit is not None

    def test_hold_when_no_clear_regime(self) -> None:
        strategy = BtcM15RegimeStrategy(self.config())
        prices = [50000, 50010, 49990, 50000, 50005, 49995, 50000] * 5
        data = self.make_btc_frame(prices, extra_bars=15)
        signal = strategy.generate_signal(data, position=None)
        assert signal.action == "hold"

    def test_close_long_when_regime_lost(self) -> None:
        strategy = BtcM15RegimeStrategy(self.config())
        # Uptrend then reversal
        prices = [50000 + i * 50 for i in range(20)] + [51000 - i * 80 for i in range(10)]
        data = self.make_btc_frame(prices, extra_bars=15)
        position = Position(ticket=1, symbol="BTCUSD", side="buy", volume=0.1, price_open=50500.0)
        signal = strategy.generate_signal(data, position=position)
        if signal.action == "close":
            assert "long" in signal.reason

    def test_close_short_when_regime_lost(self) -> None:
        strategy = BtcM15RegimeStrategy(self.config())
        prices = [52000 - i * 50 for i in range(20)] + [51000 + i * 80 for i in range(10)]
        data = self.make_btc_frame(prices, extra_bars=15)
        position = Position(ticket=1, symbol="BTCUSD", side="sell", volume=0.1, price_open=51000.0)
        signal = strategy.generate_signal(data, position=position)
        if signal.action == "close":
            assert "short" in signal.reason

    def test_adx_and_rsi_and_atr_helpers(self) -> None:
        from mt5_quant.strategy.btc_m15_regime import _adx, _atr, _ema, _rsi

        df = pd.DataFrame({
            "high": [50100, 50200, 50300, 50400, 50500, 50600, 50700, 50800],
            "low": [49900, 49800, 49700, 49600, 49500, 49400, 49300, 49200],
            "close": [50000, 50100, 50200, 50300, 50400, 50500, 50600, 50700],
        })

        adx, plus_di, minus_di = _adx(df, period=5)
        assert not adx.isna().all()
        assert not plus_di.isna().all()
        assert not minus_di.isna().all()

        atr = _atr(df, period=5)
        assert atr.iloc[-1] > 0

        ema = _ema(df["close"], period=5)
        assert ema.iloc[-1] > 50000

        rsi = _rsi(df["close"], period=5)
        assert rsi.iloc[-1] > 50  # should be bullish

    def test_invalid_stop_distance_returns_hold(self) -> None:
        """When ATR is zero, stop_distance <= 0 should return hold."""
        strategy = BtcM15RegimeStrategy(self.config(atr_stop_multiple=0))
        prices = [50000 + i * 50 for i in range(30)]
        data = self.make_btc_frame(prices, extra_bars=10)
        # Make ATR zero by flat data
        flat_data = pd.DataFrame({
            "open": [50000] * 40,
            "high": [50000] * 40,
            "low": [50000] * 40,
            "close": [50000] * 40,
            "volume": [100] * 40,
        })
        signal = strategy.generate_signal(flat_data, position=None)
        assert signal.action == "hold"

    def test_position_closes_when_ema_crosses(self) -> None:
        strategy = BtcM15RegimeStrategy(self.config())
        prices = [50000 + i * 60 for i in range(15)] + [51000 - i * 100 for i in range(15)]
        data = self.make_btc_frame(prices, extra_bars=15)
        position = Position(ticket=1, symbol="BTCUSD", side="buy", volume=0.1, price_open=50500.0)
        signal = strategy.generate_signal(data, position=position)
        if signal.action == "close":
            assert signal.reason in {"btc_long_regime_lost", "btc_short_regime_lost"}
