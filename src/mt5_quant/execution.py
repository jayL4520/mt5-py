"""下单、平仓与止损更新执行层。"""

from __future__ import annotations

import logging

from mt5_quant.config import AppConfig
from mt5_quant.data import Mt5Gateway
from mt5_quant.models import Position
from mt5_quant.runtime_events import RuntimeEventWriter

LOGGER = logging.getLogger(__name__)


class ExecutionEngine:
    """负责把策略动作转换成 MT5 交易请求。"""
    def __init__(
        self,
        config: AppConfig,
        gateway: Mt5Gateway,
        event_writer: RuntimeEventWriter | None = None,
        session_id: str = "",
    ) -> None:
        self.config = config
        self.gateway = gateway
        self.event_writer = event_writer
        self.session_id = session_id

    def open_market_position(
        self,
        side: str,
        volume: float,
        stop_loss: float | None,
        take_profit: float | None,
        *,
        signal_reason: str = "",
        bar_time: str = "",
    ) -> None:
        """以市价开仓，并同时附带止盈止损。"""
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
            if self.event_writer is not None:
                self.event_writer.emit(
                    "runtime_error",
                    f"开仓失败，返回码：{retcode}",
                    signal_action=side,
                    signal_reason=signal_reason,
                    bar_time=bar_time,
                    position_side=side,
                    extra={"retcode": retcode, "volume": volume},
                )
            raise RuntimeError(f"Open order failed: {retcode}")

        LOGGER.info("[session_id=%s] Opened %s %.2f lots on %s", self.session_id, side, volume, self.config.trading.symbol)
        if self.event_writer is not None:
            self.event_writer.emit(
                "position_opened",
                f"已开仓：{side} {volume:.2f} 手",
                signal_action=side,
                signal_reason=signal_reason,
                bar_time=bar_time,
                position_side=side,
                extra={
                    "volume": volume,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                },
            )

    def close_position(self, position: Position, *, signal_reason: str = "", bar_time: str = "") -> None:
        """以反向市价单平掉已有持仓。"""
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
            if self.event_writer is not None:
                self.event_writer.emit(
                    "runtime_error",
                    f"平仓失败，返回码：{retcode}",
                    signal_reason=signal_reason,
                    bar_time=bar_time,
                    position_side=position.side,
                    extra={"retcode": retcode, "ticket": position.ticket},
                )
            raise RuntimeError(f"Close position failed: {retcode}")

        LOGGER.info("[session_id=%s] Closed position %s on %s", self.session_id, position.ticket, position.symbol)
        if self.event_writer is not None:
            self.event_writer.emit(
                "position_closed",
                "已平仓",
                signal_reason=signal_reason,
                bar_time=bar_time,
                position_side=position.side,
                extra={"ticket": position.ticket, "volume": position.volume},
            )

    def update_position_stops(
        self,
        position: Position,
        stop_loss: float | None,
        take_profit: float | None,
        *,
        bar_time: str = "",
    ) -> None:
        """更新已持仓的止损止盈。"""
        lib = self.gateway._require_mt5()
        symbol_info = self.gateway.get_symbol_info()

        request = {
            "action": lib.TRADE_ACTION_SLTP,
            "position": position.ticket,
            "symbol": position.symbol,
            "sl": round(stop_loss, symbol_info.digits) if stop_loss is not None else 0.0,
            "tp": round(take_profit, symbol_info.digits) if take_profit is not None else 0.0,
        }

        result = lib.order_send(request)
        if result is None or result.retcode != lib.TRADE_RETCODE_DONE:
            retcode = getattr(result, "retcode", "unknown")
            if self.event_writer is not None:
                self.event_writer.emit(
                    "runtime_error",
                    f"止损止盈更新失败，返回码：{retcode}",
                    bar_time=bar_time,
                    position_side=position.side,
                    extra={"retcode": retcode, "ticket": position.ticket},
                )
            raise RuntimeError(f"Update stops failed: {retcode}")

        LOGGER.info(
            "[session_id=%s] Updated stops for %s: sl=%s tp=%s",
            self.session_id,
            position.ticket,
            request["sl"],
            request["tp"],
        )
        if self.event_writer is not None:
            self.event_writer.emit(
                "position_stop_updated",
                "已更新止损止盈",
                bar_time=bar_time,
                position_side=position.side,
                extra={"ticket": position.ticket, "sl": request["sl"], "tp": request["tp"]},
            )
