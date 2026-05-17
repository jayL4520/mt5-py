"""系统内通用数据结构定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SignalAction = Literal["buy", "sell", "close", "hold"]
PositionSide = Literal["buy", "sell"]


@dataclass(slots=True)
class Signal:
    action: SignalAction
    stop_loss: float | None = None
    take_profit: float | None = None
    reason: str = ""


@dataclass(slots=True)
class Position:
    ticket: int
    symbol: str
    side: PositionSide
    volume: float
    price_open: float
    stop_loss: float | None
    take_profit: float | None
    opened_at: str = ""


@dataclass(slots=True)
class BacktestTrade:
    symbol: str
    side: PositionSide
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    volume: float
    pnl: float
    exit_reason: str
