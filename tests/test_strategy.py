from __future__ import annotations

import pandas as pd

from mt5_quant.config import StrategyConfig
from mt5_quant.strategy.ma_cross_atr import MovingAverageAtrStrategy
from mt5_quant.strategy.xau_m1_momentum import XauM1MomentumStrategy


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
