"""策略与风控最小测试集。"""

from __future__ import annotations

import pandas as pd

from mt5_quant.config import SafetyConfig, StrategyConfig
from mt5_quant.guardrails import RiskSnapshot, SafetyGuard
from mt5_quant.models import Position
from mt5_quant.strategy.ma_cross_atr import MovingAverageAtrStrategy
from mt5_quant.strategy.xau_m1_momentum import XauM1MomentumStrategy
from mt5_quant.backtest import BacktestEngine


def test_ma_cross_strategy_emits_action() -> None:
    data = pd.DataFrame(
        {
            "open": [1, 2, 3, 4, 5, 6, 7, 8],
            "high": [2, 3, 4, 5, 6, 7, 8, 9],
            "low": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5],
            "close": [1, 2, 3, 4, 3, 4, 5, 6],
        }
    )
    config = StrategyConfig(
        name="ma_cross_atr",
        short_window=2,
        long_window=3,
        atr_period=2,
        atr_stop_multiple=2.0,
        reward_to_risk=2.0,
        risk_per_trade=0.01,
        ema_fast=21,
        ema_slow=55,
        rsi_period=14,
        rsi_buy_threshold=55.0,
        rsi_sell_threshold=45.0,
        breakout_lookback=20,
        take_profit_pct=0.003,
        stop_loss_pct=0.004,
    )
    strategy = MovingAverageAtrStrategy(config)
    signal = strategy.generate_signal(data, position=None)
    assert signal.action in {"buy", "sell", "hold"}


def test_xau_m1_strategy_returns_valid_signal() -> None:
    close = [
        100.0, 100.1, 100.2, 100.15, 100.25, 100.3, 100.35, 100.4, 100.45, 100.5,
        100.55, 100.6, 100.65, 100.7, 100.75, 100.8, 100.85, 100.9, 100.95, 101.0,
        101.05, 101.1, 101.15, 101.2, 101.25, 101.3, 101.35, 101.4, 101.45, 101.7,
    ]
    data = pd.DataFrame(
        {
            "open": close,
            "high": [value + 0.05 for value in close],
            "low": [value - 0.05 for value in close],
            "close": close,
        }
    )
    config = StrategyConfig(
        name="xau_m1_momentum",
        short_window=20,
        long_window=50,
        atr_period=14,
        atr_stop_multiple=2.0,
        reward_to_risk=2.0,
        risk_per_trade=0.0025,
        ema_fast=5,
        ema_slow=9,
        rsi_period=5,
        rsi_buy_threshold=55.0,
        rsi_sell_threshold=45.0,
        breakout_lookback=6,
        take_profit_pct=0.003,
        stop_loss_pct=0.004,
    )
    strategy = XauM1MomentumStrategy(config)
    signal = strategy.generate_signal(data, position=None)
    assert signal.action in {"buy", "sell", "hold"}


def test_safety_guard_blocks_news_and_direction() -> None:
    guard = SafetyGuard(
        SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["14:00-23:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=3,
            one_direction_per_day=True,
            news_blackout_windows=["2026-05-18 20:25/2026-05-18 20:45"],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        )
    )
    risk = RiskSnapshot(
        realized_pnl=0.0,
        day_start_balance=100000.0,
        current_balance=100000.0,
        consecutive_losses=0,
    )
    allowed, reason = guard.can_open_trade(pd.Timestamp("2026-05-18 20:30:00", tz="Asia/Shanghai"), risk)
    assert allowed is False
    assert reason == "news_blackout_window"

    direction_allowed, direction_reason = guard.is_direction_allowed("sell", "buy")
    assert direction_allowed is False
    assert direction_reason == "one_direction_per_day"


def test_backtest_trailing_stop_moves_up_for_long_position() -> None:
    class DummyConfig:
        class Safety:
            trailing_stop_enabled = True
            trailing_trigger_pct = 0.001
            trailing_distance_pct = 0.0005

        safety = Safety()

    engine = BacktestEngine.__new__(BacktestEngine)
    engine.config = DummyConfig()
    position = Position(
        ticket=1,
        symbol="XAUUSD",
        side="buy",
        volume=1.0,
        price_open=100.0,
        stop_loss=99.0,
        take_profit=103.0,
    )
    bar = pd.Series({"close": 100.3})
    engine._apply_trailing_stop(position, bar)
    assert position.stop_loss is not None
    assert position.stop_loss > 99.0
