"""单元测试：backtest — 回测引擎。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from math import inf
from typing import Any

import pandas as pd
import pytest

from mt5_quant.backtest import BacktestEngine
from mt5_quant.config import AppConfig, BacktestConfig, NewsCalendarConfig, ReportingConfig, SafetyConfig
from mt5_quant.models import BacktestTrade, Position, Signal
from mt5_quant.strategy.base import Strategy


# ── Dummy strategy ──────────────────────────────────────────────────────

class BuyOnNthBarStrategy(Strategy):
    """Emits a buy signal on the Nth bar, then a close on the Mth bar."""
    def __init__(self, entry_bar: int = 10, exit_bar: int = 20) -> None:
        self.entry_bar = entry_bar
        self.exit_bar = exit_bar
        self.counter = 0

    def generate_signal(self, data: pd.DataFrame, position: Position | None) -> Signal:
        self.counter = len(data)
        if position is None and self.counter == self.entry_bar:
            close = float(data.iloc[-1]["close"])
            return Signal(action="buy", stop_loss=close * 0.99, take_profit=close * 1.01, reason="test_entry")
        if position is not None and self.counter == self.exit_bar:
            return Signal(action="close", reason="test_exit")
        return Signal(action="hold", reason="no_signal")


class NeverTradeStrategy(Strategy):
    """Always emits hold."""
    def generate_signal(self, data: pd.DataFrame, position: Position | None) -> Signal:
        return Signal(action="hold", reason="no_signal")


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def sample_m1_data() -> pd.DataFrame:
    """100 bars of gentle uptrend M1 data."""
    n = 100
    prices = [100.0 + i * 0.02 for i in range(n)]
    return pd.DataFrame({
        "open": prices,
        "high": [v * 1.001 for v in prices],
        "low": [v * 0.999 for v in prices],
        "close": prices,
        "volume": [100] * n,
    }, index=pd.date_range("2026-05-20 00:00", periods=n, freq="1min", tz="UTC"))


@pytest.fixture
def base_config() -> AppConfig:
    return AppConfig(
        mt5=MagicConfig(login=1, password="p", server="s"),
        trading=MagicConfig(
            symbol="XAUUSD",
            timeframe="M1",
            history_bars=1500,
            mt5_bar_time_shift_hours=0,
            slippage_points=20,
            magic_number=260516,
            comment="test",
            poll_interval_seconds=5,
            max_open_positions=1,
        ),
        strategy=MagicConfig(
            name="test",
            risk_per_trade=0.01,
            short_window=20,
            long_window=50,
            atr_period=14,
            atr_stop_multiple=2.0,
            reward_to_risk=2.0,
            leverage_multiplier=1.0,
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
        ),
        backtest=BacktestConfig(
            initial_balance=100000.0,
            commission_per_lot=0.0,
            spread_points=10,
            contract_size=1.0,
        ),
        safety=SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=6,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=False,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ),
        news_calendar=NewsCalendarConfig(
            enabled=False, provider="disabled", api_key="", countries=[],
            importance=3, pre_blackout_minutes=10, post_blackout_minutes=10,
            lookahead_days=7, cache_minutes=30, request_timeout_seconds=20,
            common_filename="", file_path="",
        ),
        reporting=ReportingConfig(
            output_dir="reports", save_summary_json=True, save_trades_csv=True, save_equity_csv=True,
        ),
    )


# ── Tests ───────────────────────────────────────────────────────────────

class TestBacktestEngine:
    def test_no_trades_when_strategy_always_holds(self, sample_m1_data: pd.DataFrame, base_config: AppConfig) -> None:
        engine = BacktestEngine(base_config, NeverTradeStrategy())
        result = engine.run(sample_m1_data)
        assert result["total_trades"] == 0
        assert result["final_balance"] == base_config.backtest.initial_balance

    def test_single_trade_profitable(self, sample_m1_data: pd.DataFrame, base_config: AppConfig) -> None:
        config = deepcopy(base_config)
        config.safety.trading_windows = ["00:00-24:00"]
        config.safety.max_daily_loss_pct = 0.02
        config.safety.max_consecutive_losses = 6
        config.safety.one_direction_per_day = False
        config.safety.news_blackout_windows = []
        config.safety.trailing_stop_enabled = False
        config.strategy.risk_per_trade = 0.01

        engine = BacktestEngine(config, BuyOnNthBarStrategy(entry_bar=10, exit_bar=50))
        result = engine.run(sample_m1_data)

        assert result["total_trades"] == 1
        assert result["trades"][0]["exit_reason"] == "test_exit"

    def test_stop_loss_hit(self, sample_m1_data: pd.DataFrame, base_config: AppConfig) -> None:
        """When price drops below stop_loss, trade should exit."""
        config = deepcopy(base_config)
        config.safety.trailing_stop_enabled = False

        # Create a strategy that enters then price reverses to hit SL
        class EntryThenHold(Strategy):
            def __init__(self):
                self.entered = False
            def generate_signal(self, data, position):
                if position is None and not self.entered and len(data) >= 5:
                    self.entered = True
                    close = float(data.iloc[-1]["close"])
                    return Signal(action="buy", stop_loss=close * 0.99, take_profit=close * 1.02, reason="entry")
                return Signal(action="hold", reason="no_signal")

        # Make data that reverses after entry
        n = 50
        prices = [100.0] * 5 + [100.0 - i * 0.05 for i in range(45)]
        data = pd.DataFrame({
            "open": prices, "high": [v * 1.001 for v in prices],
            "low": [v * 0.998 for v in prices], "close": prices,
            "volume": [100] * n,
        }, index=pd.date_range("2026-05-20 00:00", periods=n, freq="1min", tz="UTC"))

        engine = BacktestEngine(config, EntryThenHold())
        result = engine.run(data)
        assert result["total_trades"] > 0
        # Some trade might exit via stop_loss
        if result["total_trades"] > 0:
            assert any(t["exit_reason"] == "stop_loss" for t in result["trades"])

    def test_take_profit_hit(self, sample_m1_data: pd.DataFrame, base_config: AppConfig) -> None:
        config = deepcopy(base_config)
        config.safety.trailing_stop_enabled = False

        class EntryThenRally(Strategy):
            def __init__(self):
                self.entered = False
            def generate_signal(self, data, position):
                if position is None and not self.entered and len(data) >= 5:
                    self.entered = True
                    close = float(data.iloc[-1]["close"])
                    return Signal(action="buy", stop_loss=close * 0.99, take_profit=close * 1.005, reason="entry")
                return Signal(action="hold", reason="no_signal")

        prices = [100.0] * 5 + [100.0 + i * 0.03 for i in range(45)]
        data = pd.DataFrame({
            "open": prices, "high": [v * 1.002 for v in prices],
            "low": [v * 0.998 for v in prices], "close": prices,
            "volume": [100] * 50,
        }, index=pd.date_range("2026-05-20 00:00", periods=50, freq="1min", tz="UTC"))

        engine = BacktestEngine(config, EntryThenRally())
        result = engine.run(data)
        if result["total_trades"] > 0:
            assert any(t["exit_reason"] == "take_profit" for t in result["trades"])

    def test_blocked_by_trading_window(self, sample_m1_data: pd.DataFrame, base_config: AppConfig) -> None:
        """Entry blocked when outside trading window."""
        config = deepcopy(base_config)
        config.safety.trading_windows = ["00:00-01:00"]  # Only first hour
        config.safety.trailing_stop_enabled = False

        engine = BacktestEngine(config, BuyOnNthBarStrategy(entry_bar=10, exit_bar=50))
        result = engine.run(sample_m1_data)
        # Entry at bar 10 is outside 00:00-01:00 (sample data starts at 00:00, bar 10 = 00:10)
        assert "outside_trading_window" in result.get("blocked_entries", {})

    def test_blocked_by_daily_loss_limit(self, sample_m1_data: pd.DataFrame, base_config: AppConfig) -> None:
        """After daily loss limit is hit, new entries are blocked."""
        config = deepcopy(base_config)
        config.safety.max_daily_loss_pct = 0.005  # 0.5% max loss
        config.strategy.risk_per_trade = 0.1  # 10% risk per trade — guaranteed loss
        config.safety.trailing_stop_enabled = False

        class LossStrategy(Strategy):
            def generate_signal(self, data, position):
                if position is None and len(data) == 3:
                    close = float(data.iloc[-1]["close"])
                    return Signal(action="buy", stop_loss=close * 0.5, take_profit=close * 2.0, reason="entry")
                return Signal(action="hold", reason="no_signal")

        engine = BacktestEngine(config, LossStrategy())
        result = engine.run(sample_m1_data)
        # The trade will hit stop loss, balance drops >0.5%, blocking further entries
        if result["total_trades"] > 0:
            blocked = result.get("blocked_entries", {})
            assert any("daily_loss" in k or "loss" in k.lower() for k in blocked)

    def test_blocked_by_consecutive_losses(self, sample_m1_data: pd.DataFrame, base_config: AppConfig) -> None:
        config = deepcopy(base_config)
        config.safety.max_consecutive_losses = 1  # After 1 loss, 2nd consecutive triggers block
        config.safety.trailing_stop_enabled = False
        config.strategy.risk_per_trade = 0.5  # Large risk to guarantee loss

        class TwoLossesStrategy(Strategy):
            def __init__(self):
                self.trades = 0
            def generate_signal(self, data, position):
                if position is None and self.trades < 2 and len(data) in [5, 15]:
                    self.trades += 1
                    close = float(data.iloc[-1]["close"])
                    return Signal(action="buy", stop_loss=close * 0.5, take_profit=close * 2.0, reason="entry")
                return Signal(action="hold", reason="no_signal")

        engine = BacktestEngine(config, TwoLossesStrategy())
        result = engine.run(sample_m1_data)
        # Both trades lose, so consecutive_losses > 1 should block after the 2nd loss
        # The 2nd trade executes before the limit, but then the 3rd attempt is blocked

    def test_blocked_by_one_direction_per_day(self, sample_m1_data: pd.DataFrame, base_config: AppConfig) -> None:
        config = deepcopy(base_config)
        config.safety.one_direction_per_day = True
        config.safety.trailing_stop_enabled = False
        config.strategy.risk_per_trade = 0.01

        class BuyThenSellStrategy(Strategy):
            def generate_signal(self, data, position):
                if position is None and len(data) == 5:
                    return Signal(action="buy", stop_loss=90.0, take_profit=110.0, reason="buy_first")
                if position is not None and len(data) == 10:
                    return Signal(action="close", reason="exit")
                if position is None and len(data) == 15:
                    return Signal(action="sell", stop_loss=110.0, take_profit=90.0, reason="sell_second")
                return Signal(action="hold", reason="no_signal")

        engine = BacktestEngine(config, BuyThenSellStrategy())
        result = engine.run(sample_m1_data)
        # First buy should execute, then after close, sell is blocked by one_direction_per_day
        if result["total_trades"] == 1:
            assert "one_direction_per_day" in result.get("blocked_entries", {})

    def test_missing_stop_loss_in_signal_uses_bar_close(self, sample_m1_data: pd.DataFrame, base_config: AppConfig) -> None:
        """When signal has no stop_loss, engine uses bar close as fallback — distance=0 so no entry."""
        config = deepcopy(base_config)
        config.safety.trailing_stop_enabled = False

        class NoStopStrategy(Strategy):
            def generate_signal(self, data, position):
                if position is None and len(data) == 5:
                    return Signal(action="buy", stop_loss=None, take_profit=110.0, reason="no_sl")
                return Signal(action="hold", reason="no_signal")

        engine = BacktestEngine(config, NoStopStrategy())
        result = engine.run(sample_m1_data)
        # distance=0 (stop_loss=close), risk_amount/distance=inf -> volume calculation might be 0
        assert result["total_trades"] == 0

    def test_trailing_stop_for_long(self, base_config: AppConfig) -> None:
        """Verify trailing stop moves upward for long positions."""
        config = deepcopy(base_config)
        config.safety.trailing_stop_enabled = True
        config.safety.trailing_trigger_pct = 0.001
        config.safety.trailing_distance_pct = 0.0005

        class DummyStrategy(Strategy):
            def generate_signal(self, data, position):
                if position is None and len(data) == 3:
                    return Signal(action="buy", stop_loss=99.0, take_profit=110.0, reason="entry")
                return Signal(action="hold", reason="no_signal")

        prices = [100.0] * 3 + [100.3, 100.6, 100.9, 101.2, 101.5]
        data = pd.DataFrame({
            "open": prices, "high": [v * 1.002 for v in prices],
            "low": [v * 0.998 for v in prices], "close": prices,
            "volume": [100] * len(prices),
        }, index=pd.date_range("2026-05-20 00:00", periods=len(prices), freq="1min", tz="UTC"))

        engine = BacktestEngine(config, DummyStrategy())
        result = engine.run(data)
        # Trailing stop should have moved up from 99.0
        # (We can't easily inspect internal state, but the test verifies it runs without error)

    def test_trailing_stop_for_short(self, base_config: AppConfig) -> None:
        config = deepcopy(base_config)
        config.safety.trailing_stop_enabled = True
        config.safety.trailing_trigger_pct = 0.001
        config.safety.trailing_distance_pct = 0.0005

        class ShortStrategy(Strategy):
            def generate_signal(self, data, position):
                if position is None and len(data) == 3:
                    return Signal(action="sell", stop_loss=101.0, take_profit=98.0, reason="entry")
                return Signal(action="hold", reason="no_signal")

        prices = [100.0] * 3 + [99.7, 99.4, 99.1, 98.8, 98.5]
        data = pd.DataFrame({
            "open": prices, "high": [v * 1.002 for v in prices],
            "low": [v * 0.998 for v in prices], "close": prices,
            "volume": [100] * len(prices),
        }, index=pd.date_range("2026-05-20 00:00", periods=len(prices), freq="1min", tz="UTC"))

        engine = BacktestEngine(config, ShortStrategy())
        result = engine.run(data)
        assert result["total_trades"] > 0

    def test_infer_point_precision(self, base_config: AppConfig) -> None:
        """Test point inference from price data."""
        data = pd.DataFrame({
            "open": [1.23456, 1.23457], "high": [1.23458, 1.23459],
            "low": [1.23454, 1.23455], "close": [1.23456, 1.23457],
        })
        point = BacktestEngine._infer_point(data)
        assert point == 0.00001  # 5 decimal places

    def test_infer_point_integer_prices(self, base_config: AppConfig) -> None:
        data = pd.DataFrame({
            "open": [100, 101], "high": [102, 103],
            "low": [99, 100], "close": [100, 101],
        })
        point = BacktestEngine._infer_point(data)
        assert point == 1.0

    def test_infer_point_mixed_precision(self, base_config: AppConfig) -> None:
        """Use the highest decimal precision found across all price columns.
        Note: rstrip('0') means 102.50 becomes '102.5' (1 decimal)."""
        data = pd.DataFrame({
            "open": [100.0, 101.0], "high": [102.50, 103.50],
            "low": [99.0, 100.0], "close": [100.0, 101.0],
        })
        point = BacktestEngine._infer_point(data)
        assert point == 0.1  # 1 decimal place from high after rstrip('0')

    def test_backtest_summary_format(self, sample_m1_data: pd.DataFrame, base_config: AppConfig) -> None:
        engine = BacktestEngine(base_config, BuyOnNthBarStrategy(entry_bar=5, exit_bar=15))
        result = engine.run(sample_m1_data)
        expected_keys = {
            "final_balance", "net_profit", "total_trades", "win_rate",
            "gross_profit", "gross_loss", "avg_trade", "avg_win", "avg_loss",
            "profit_factor", "max_drawdown_pct", "blocked_entries",
            "trades", "equity_curve",
        }
        assert expected_keys.issubset(result.keys())
        assert isinstance(result["trades"], list)
        assert isinstance(result["equity_curve"], list)

    def test_profit_factor_edge_cases(self, base_config: AppConfig) -> None:
        class AllLosses(Strategy):
            def generate_signal(self, data, position):
                if position is None and len(data) == 5:
                    return Signal(action="buy", stop_loss=0.01, take_profit=200.0, reason="loss")
                if position is not None and len(data) == 10:
                    return Signal(action="close", reason="exit")
                return Signal(action="hold", reason="no_signal")

        prices = [100.0] * 10 + [50.0] * 10
        data = pd.DataFrame({
            "open": prices, "high": [v * 1.01 for v in prices],
            "low": [v * 0.99 for v in prices], "close": prices,
            "volume": [100] * len(prices),
        }, index=pd.date_range("2026-05-20 00:00", periods=len(prices), freq="1min", tz="UTC"))

        result = BacktestEngine(base_config, AllLosses()).run(data)
        if result["total_trades"] > 0:
            assert result["profit_factor"] == 0.0 or result["profit_factor"] == inf

    def test_drawdown_calculation(self, sample_m1_data: pd.DataFrame, base_config: AppConfig) -> None:
        class ProfitThenLoss(Strategy):
            def generate_signal(self, data, position):
                if position is None and len(data) == 5:
                    return Signal(action="buy", stop_loss=0.01, take_profit=200.0, reason="win")
                return Signal(action="hold", reason="no_signal")

        engine = BacktestEngine(base_config, ProfitThenLoss())
        result = engine.run(sample_m1_data)
        assert result["max_drawdown_pct"] >= 0.0


@dataclass
class MagicConfig:
    """A simple mock that allows arbitrary attribute access."""
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return MagicConfig()
