"""单元测试：risk — 仓位管理。"""

from __future__ import annotations

import pytest

from mt5_quant.risk import RiskManager


# ── Mock gateway ────────────────────────────────────────────────────────

class MockAccountInfo:
    balance = 100000.0


class MockSymbolInfo:
    volume_min = 0.01
    volume_max = 100.0
    volume_step = 0.01
    trade_contract_size = 1.0


class MockGateway:
    def __init__(self, loss_per_lot: float = 100.0, balance: float = 100000.0):
        self._loss_per_lot = loss_per_lot
        self._balance = balance

    def get_account_info(self) -> MockAccountInfo:
        return MockAccountInfo()

    def get_symbol_info(self) -> MockSymbolInfo:
        return MockSymbolInfo()

    def order_calc_loss_per_lot(self, side: str, entry: float, stop_loss: float) -> float:
        return self._loss_per_lot


class MockConfig:
    class Strategy:
        risk_per_trade = 0.01
        leverage_multiplier = 1.0

    strategy = Strategy()


# ── Tests ───────────────────────────────────────────────────────────────

class TestRiskManager:
    def test_calculate_volume_basic(self) -> None:
        """risk_amount = 100000 * 0.01 = 1000. loss_per_lot = 100. volume = 1000/100 = 10."""
        mgr = RiskManager(MockConfig(), MockGateway(loss_per_lot=100.0))
        volume = mgr.calculate_volume("buy", 100.0, 99.0)
        assert volume == 10.0

    def test_leverage_multiplier_applied(self) -> None:
        class ConfigWithLeverage:
            class Strategy:
                risk_per_trade = 0.01
                leverage_multiplier = 2.5
            strategy = Strategy()

        mgr = RiskManager(ConfigWithLeverage(), MockGateway(loss_per_lot=100.0))
        volume = mgr.calculate_volume("buy", 100.0, 99.0)
        assert volume == 25.0  # 10 * 2.5

    def test_zero_risk_amount_returns_zero(self) -> None:
        class ConfigZeroRisk:
            class Strategy:
                risk_per_trade = 0.0
                leverage_multiplier = 1.0
            strategy = StrategyZeroRisk = Strategy()

        mgr = RiskManager(ConfigZeroRisk(), MockGateway())
        volume = mgr.calculate_volume("buy", 100.0, 99.0)
        assert volume == 0.0

    def test_loss_per_lot_fallback_to_distance(self) -> None:
        """When order_calc_loss_per_lot returns 0, fall back to distance * contract_size."""
        class GatewayNoCalc:
            def get_account_info(self):
                return MockAccountInfo()
            def get_symbol_info(self):
                return MockSymbolInfo()
            def order_calc_loss_per_lot(self, side, entry, stop_loss):
                return 0.0  # MT5 calculation failed

        mgr = RiskManager(MockConfig(), GatewayNoCalc())
        # distance = 1.0, contract_size = 1.0, loss_per_lot = 1.0
        # risk_amount = 1000, volume = 1000 / 1.0 = 1000, clipped to max=100
        volume = mgr.calculate_volume("buy", 100.0, 99.0)
        assert volume == 100.0  # clipped to volume_max

    def test_zero_distance_returns_zero(self) -> None:
        """When entry == stop_loss, distance = 0 -> volume = 0."""
        mgr = RiskManager(MockConfig(), MockGateway())
        volume = mgr.calculate_volume("buy", 100.0, 100.0)
        assert volume == 0.0

    def test_volume_normalized_to_step(self) -> None:
        """Raw volume of 10.123 should be normalized to 10.12 with step=0.01."""
        normalized = RiskManager._normalize_volume(10.123, 0.01, 100.0, 0.01)
        assert normalized == 10.12

    def test_volume_below_min_returns_zero(self) -> None:
        normalized = RiskManager._normalize_volume(0.001, 0.01, 100.0, 0.01)
        assert normalized == 0.0

    def test_volume_clipped_to_max(self) -> None:
        normalized = RiskManager._normalize_volume(200.0, 0.01, 100.0, 0.01)
        assert normalized == 100.0

    def test_normalize_with_zero_step_returns_clipped(self) -> None:
        normalized = RiskManager._normalize_volume(15.5, 0.01, 100.0, 0.0)
        assert normalized == 15.5

    def test_normalize_rounding_precision(self) -> None:
        normalized = RiskManager._normalize_volume(1.23456789, 0.01, 100.0, 0.01)
        assert normalized == 1.23
