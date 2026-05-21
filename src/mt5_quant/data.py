"""MT5 数据访问层。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd

from mt5_quant.config import AppConfig, TIMEFRAME_ALIASES
from mt5_quant.models import Position

LOGGER = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None


class Mt5UnavailableError(RuntimeError):
    pass


class Mt5Gateway:
    """对 MetaTrader5 Python 接口做轻量封装。"""
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _require_mt5(self) -> Any:
        if mt5 is None:
            raise Mt5UnavailableError("MetaTrader5 package is not installed.")
        return mt5

    def connect(self) -> None:
        """初始化 MT5 并选中交易品种。"""
        lib = self._require_mt5()
        kwargs = {
            "login": self.config.mt5.login,
            "password": self.config.mt5.password,
            "server": self.config.mt5.server,
            "timeout": self.config.mt5.timeout,
            "portable": self.config.mt5.portable,
        }

        if self.config.mt5.path:
            initialized = lib.initialize(path=self.config.mt5.path, **kwargs)
        else:
            initialized = lib.initialize(**kwargs)
        if not initialized:
            code, message = lib.last_error()
            raise RuntimeError(f"MT5 initialize failed: {code} {message}")

        if not lib.symbol_select(self.config.trading.symbol, True):
            code, message = lib.last_error()
            raise RuntimeError(f"Failed to select symbol {self.config.trading.symbol}: {code} {message}")

        LOGGER.info("Connected to MT5 account %s on %s", self.config.mt5.login, self.config.mt5.server)

    def shutdown(self) -> None:
        lib = self._require_mt5()
        lib.shutdown()

    def timeframe(self) -> int:
        lib = self._require_mt5()
        return getattr(lib, TIMEFRAME_ALIASES[self.config.trading.timeframe])

    def get_rates(self, bars: int | None = None) -> pd.DataFrame:
        """获取历史 K 线并转成 DataFrame。"""
        lib = self._require_mt5()
        bars = bars or self.config.trading.history_bars
        rates = lib.copy_rates_from_pos(self.config.trading.symbol, self.timeframe(), 0, bars)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No rates returned for {self.config.trading.symbol}")

        frame = pd.DataFrame(rates)
        frame["time"] = self._convert_rate_time(
            frame["time"],
            self.config.trading.mt5_bar_time_shift_hours,
        )
        frame = frame.rename(columns={"tick_volume": "volume"})
        return frame.set_index("time")

    @staticmethod
    def _convert_rate_time(raw_time, shift_hours: float) -> pd.Series:
        """把 MT5 K 线时间转成 UTC，并按配置修正券商服务器时区偏移。"""
        converted = pd.to_datetime(raw_time, unit="s", utc=True)
        if shift_hours:
            converted = converted - pd.to_timedelta(shift_hours, unit="h")
        return converted

    def get_positions(self) -> list[Position]:
        """读取当前策略名下的持仓。"""
        lib = self._require_mt5()
        raw_positions = lib.positions_get(symbol=self.config.trading.symbol) or []
        positions: list[Position] = []
        for pos in raw_positions:
            if getattr(pos, "magic", None) != self.config.trading.magic_number:
                continue
            side = "buy" if pos.type == lib.POSITION_TYPE_BUY else "sell"
            positions.append(
                Position(
                    ticket=int(pos.ticket),
                    symbol=pos.symbol,
                    side=side,
                    volume=float(pos.volume),
                    price_open=float(pos.price_open),
                    stop_loss=float(pos.sl) if pos.sl else None,
                    take_profit=float(pos.tp) if pos.tp else None,
                    opened_at=str(getattr(pos, "time", "")),
                )
            )
        return positions

    def get_symbol_info(self) -> Any:
        lib = self._require_mt5()
        info = lib.symbol_info(self.config.trading.symbol)
        if info is None:
            raise RuntimeError(f"Cannot load symbol info for {self.config.trading.symbol}")
        return info

    def get_tick(self) -> Any:
        lib = self._require_mt5()
        tick = lib.symbol_info_tick(self.config.trading.symbol)
        if tick is None:
            raise RuntimeError(f"Cannot load tick for {self.config.trading.symbol}")
        return tick

    def get_account_info(self) -> Any:
        lib = self._require_mt5()
        info = lib.account_info()
        if info is None:
            raise RuntimeError("Cannot load account info.")
        return info

    def order_calc_loss_per_lot(self, side: str, entry: float, stop_loss: float) -> float:
        """估算 1 手仓位从开仓价打到止损价的亏损。"""
        lib = self._require_mt5()
        order_type = lib.ORDER_TYPE_BUY if side == "buy" else lib.ORDER_TYPE_SELL
        result = lib.order_calc_profit(order_type, self.config.trading.symbol, 1.0, entry, stop_loss)
        if result is None:
            return 0.0
        return abs(float(result))

    def get_deals_range(self, date_from: datetime, date_to: datetime) -> list[dict[str, float | int | str]]:
        """读取某个时间区间内的历史成交。"""
        lib = self._require_mt5()
        raw_deals = lib.history_deals_get(date_from, date_to) or []
        deals: list[dict[str, float | int | str]] = []
        for deal in raw_deals:
            if getattr(deal, "symbol", "") != self.config.trading.symbol:
                continue
            if getattr(deal, "magic", None) != self.config.trading.magic_number:
                continue
            profit = float(getattr(deal, "profit", 0.0))
            commission = float(getattr(deal, "commission", 0.0))
            swap = float(getattr(deal, "swap", 0.0))
            deal_type = int(getattr(deal, "type", -1))
            side = "buy" if deal_type == lib.DEAL_TYPE_BUY else "sell" if deal_type == lib.DEAL_TYPE_SELL else "unknown"
            deals.append(
                {
                    "ticket": int(getattr(deal, "ticket", 0)),
                    "time": int(getattr(deal, "time", 0)),
                    "entry": int(getattr(deal, "entry", -1)),
                    "side": side,
                    "pnl": profit + commission + swap,
                }
            )
        deals.sort(key=lambda item: int(item["time"]))
        return deals
