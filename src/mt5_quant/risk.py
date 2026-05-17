"""仓位风险控制模块。"""

from __future__ import annotations

import math

from mt5_quant.config import AppConfig
from mt5_quant.data import Mt5Gateway


class RiskManager:
    """按单笔风险比例计算下单手数。"""
    def __init__(self, config: AppConfig, gateway: Mt5Gateway) -> None:
        self.config = config
        self.gateway = gateway

    def calculate_volume(self, side: str, entry: float, stop_loss: float) -> float:
        """根据账户余额和止损距离计算标准化手数。"""
        account = self.gateway.get_account_info()
        info = self.gateway.get_symbol_info()
        risk_amount = float(account.balance) * self.config.strategy.risk_per_trade
        if risk_amount <= 0:
            return 0.0

        loss_per_lot = self.gateway.order_calc_loss_per_lot(side=side, entry=entry, stop_loss=stop_loss)
        if loss_per_lot <= 0:
            distance = abs(entry - stop_loss)
            if distance <= 0:
                return 0.0
            loss_per_lot = distance * float(info.trade_contract_size)

        raw_volume = risk_amount / loss_per_lot
        return self._normalize_volume(raw_volume, info.volume_min, info.volume_max, info.volume_step)

    @staticmethod
    def _normalize_volume(volume: float, minimum: float, maximum: float, step: float) -> float:
        if volume < minimum:
            return 0.0
        clipped = min(volume, maximum)
        steps = math.floor((clipped - minimum) / step) if step > 0 else 0
        normalized = minimum + (steps * step) if step > 0 else clipped
        return round(normalized, 8)
