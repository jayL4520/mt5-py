from __future__ import annotations

import logging

from mt5_quant.config import AppConfig
from mt5_quant.data import Mt5Gateway
from mt5_quant.models import Position

LOGGER = logging.getLogger(__name__)


class ExecutionEngine:
    def __init__(self, config: AppConfig, gateway: Mt5Gateway) -> None:
        self.config = config
        self.gateway = gateway

    def open_market_position(
        self,
        side: str,
        volume: float,
        stop_loss: float | None,
        take_profit: float | None,
    ) -> None:
        lib = self.gateway._require_mt5()
        tick = self.gateway.get_tick()
        symbol_info = self.gateway.get_symbol_info()
        price = tick.ask if side == "buy" else tick.bid
        order_type = lib.ORDER_TYPE_BUY if side == "buy" else lib.ORDER_TYPE_SELL

        request = {
            "action": lib.TRADE_ACTION_DEAL,
            "symbol": self.config.trading.symbol,
            "volume": volume,
            "type": order_type,
            "price": round(price, symbol_info.digits),
            "sl": round(stop_loss, symbol_info.digits) if stop_loss is not None else 0.0,
            "tp": round(take_profit, symbol_info.digits) if take_profit is not None else 0.0,
            "deviation": self.config.trading.slippage_points,
            "magic": self.config.trading.magic_number,
            "comment": self.config.trading.comment,
            "type_time": lib.ORDER_TIME_GTC,
            "type_filling": getattr(lib, "ORDER_FILLING_IOC", 1),
        }

        result = lib.order_send(request)
        if result is None or result.retcode != lib.TRADE_RETCODE_DONE:
            retcode = getattr(result, "retcode", "unknown")
            raise RuntimeError(f"Open order failed: {retcode}")

        LOGGER.info("Opened %s %.2f lots on %s", side, volume, self.config.trading.symbol)

    def close_position(self, position: Position) -> None:
        lib = self.gateway._require_mt5()
        tick = self.gateway.get_tick()
        symbol_info = self.gateway.get_symbol_info()
        is_buy = position.side == "buy"
        price = tick.bid if is_buy else tick.ask
        order_type = lib.ORDER_TYPE_SELL if is_buy else lib.ORDER_TYPE_BUY

        request = {
            "action": lib.TRADE_ACTION_DEAL,
            "position": position.ticket,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": order_type,
            "price": round(price, symbol_info.digits),
            "deviation": self.config.trading.slippage_points,
            "magic": self.config.trading.magic_number,
            "comment": f"{self.config.trading.comment}-close",
            "type_time": lib.ORDER_TIME_GTC,
            "type_filling": getattr(lib, "ORDER_FILLING_IOC", 1),
        }

        result = lib.order_send(request)
        if result is None or result.retcode != lib.TRADE_RETCODE_DONE:
            retcode = getattr(result, "retcode", "unknown")
            raise RuntimeError(f"Close position failed: {retcode}")

        LOGGER.info("Closed position %s on %s", position.ticket, position.symbol)
