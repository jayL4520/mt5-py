"""单元测试：models — 系统内通用数据结构。"""

from __future__ import annotations

import pickle

from mt5_quant.models import BacktestTrade, Position, Signal


class TestSignal:
    def test_default_signal_is_hold(self) -> None:
        s = Signal(action="hold")
        assert s.action == "hold"
        assert s.stop_loss is None
        assert s.take_profit is None
        assert s.reason == ""

    def test_buy_signal_with_stops(self) -> None:
        s = Signal(action="buy", stop_loss=99.0, take_profit=103.0, reason="bull_cross")
        assert s.action == "buy"
        assert s.stop_loss == 99.0
        assert s.take_profit == 103.0
        assert s.reason == "bull_cross"

    def test_sell_signal(self) -> None:
        s = Signal(action="sell", stop_loss=101.0, take_profit=97.0, reason="bear_cross")
        assert s.action == "sell"
        assert s.stop_loss == 101.0
        assert s.take_profit == 97.0

    def test_close_signal(self) -> None:
        s = Signal(action="close", reason="momentum_lost")
        assert s.action == "close"
        assert s.reason == "momentum_lost"

    def test_signal_is_dataclass_and_picklable(self) -> None:
        s = Signal(action="buy", stop_loss=99.0, take_profit=103.0, reason="test")
        restored = pickle.loads(pickle.dumps(s))
        assert restored.action == "buy"
        assert restored.stop_loss == 99.0

    def test_signal_uses_slots(self) -> None:
        s = Signal(action="hold")
        with pytest.raises(AttributeError):
            s.non_existent_attr = 1  # type: ignore[attr-defined]


class TestPosition:
    def test_full_position(self) -> None:
        p = Position(
            ticket=1001,
            symbol="XAUUSD",
            side="buy",
            volume=0.1,
            price_open=2000.0,
            stop_loss=1990.0,
            take_profit=2020.0,
            opened_at="2026-05-20 10:00:00",
        )
        assert p.ticket == 1001
        assert p.symbol == "XAUUSD"
        assert p.side == "buy"
        assert p.volume == 0.1
        assert p.price_open == 2000.0
        assert p.opened_at == "2026-05-20 10:00:00"

    def test_position_without_stops(self) -> None:
        p = Position(
            ticket=1002,
            symbol="BTCUSD",
            side="sell",
            volume=1.0,
            price_open=50000.0,
            stop_loss=None,
            take_profit=None,
        )
        assert p.stop_loss is None
        assert p.take_profit is None
        assert p.opened_at == ""

    def test_position_is_picklable(self) -> None:
        p = Position(ticket=1, symbol="XAUUSD", side="buy", volume=0.1, price_open=2000.0)
        restored = pickle.loads(pickle.dumps(p))
        assert restored.ticket == 1
        assert restored.side == "buy"

    def test_position_uses_slots(self) -> None:
        p = Position(ticket=1, symbol="XAUUSD", side="buy", volume=0.1, price_open=2000.0)
        with pytest.raises(AttributeError):
            p.non_existent = True


class TestBacktestTrade:
    def test_full_backtest_trade(self) -> None:
        t = BacktestTrade(
            symbol="XAUUSD",
            side="buy",
            entry_time="2026-05-20 10:00:00",
            exit_time="2026-05-20 11:00:00",
            entry_price=2000.0,
            exit_price=2010.0,
            volume=0.1,
            pnl=100.0,
            exit_reason="take_profit",
        )
        assert t.symbol == "XAUUSD"
        assert t.side == "buy"
        assert t.pnl == 100.0
        assert t.exit_reason == "take_profit"

    def test_losing_trade(self) -> None:
        t = BacktestTrade(
            symbol="XAUUSD",
            side="buy",
            entry_time="2026-05-20 10:00:00",
            exit_time="2026-05-20 10:30:00",
            entry_price=2000.0,
            exit_price=1990.0,
            volume=0.1,
            pnl=-100.0,
            exit_reason="stop_loss",
        )
        assert t.pnl < 0
        assert t.exit_reason == "stop_loss"

    def test_backtest_trade_uses_slots(self) -> None:
        t = BacktestTrade(
            symbol="XAUUSD", side="sell", entry_time="t1", exit_time="t2",
            entry_price=100.0, exit_price=99.0, volume=0.1, pnl=10.0, exit_reason="tp",
        )
        with pytest.raises(AttributeError):
            t.non_existent = "x"


import pytest  # noqa: E402 (needed for the slot tests)
