"""策略基类定义。"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from mt5_quant.models import Position, Signal


class Strategy(ABC):
    """所有策略都需要实现的统一接口。"""
    @abstractmethod
    def generate_signal(self, data: pd.DataFrame, position: Position | None) -> Signal:
        raise NotImplementedError
