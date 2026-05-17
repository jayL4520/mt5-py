"""交易时段、新闻黑窗与方向限制守卫。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from mt5_quant.config import SafetyConfig


@dataclass(slots=True)
class RiskSnapshot:
    realized_pnl: float
    day_start_balance: float
    current_balance: float
    consecutive_losses: int

    @property
    def daily_loss_pct(self) -> float:
        if self.day_start_balance <= 0:
            return 0.0
        loss = max(0.0, self.day_start_balance - self.current_balance)
        return loss / self.day_start_balance


class SafetyGuard:
    def __init__(self, config: SafetyConfig) -> None:
        self.config = config
        self.timezone = ZoneInfo(config.timezone)
        self.windows = [self._parse_window(value) for value in config.trading_windows]
        self.news_windows = [self._parse_news_window(value) for value in config.news_blackout_windows]
        self.dynamic_news_windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    def is_trading_time(self, timestamp: pd.Timestamp | datetime) -> bool:
        local_ts = self.to_local_timestamp(timestamp)
        minute_of_day = local_ts.hour * 60 + local_ts.minute
        return any(self._window_contains(start, end, minute_of_day) for start, end in self.windows)

    def to_local_timestamp(self, timestamp: pd.Timestamp | datetime) -> pd.Timestamp:
        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert(self.timezone)

    def current_day_bounds_utc(self, now: datetime | None = None) -> tuple[datetime, datetime]:
        current = now or datetime.now(timezone.utc)
        local_now = current.astimezone(self.timezone)
        start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + pd.Timedelta(days=1)
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    def local_day_key(self, timestamp: pd.Timestamp | datetime) -> str:
        return self.to_local_timestamp(timestamp).strftime("%Y-%m-%d")

    def can_open_trade(self, timestamp: pd.Timestamp | datetime, risk: RiskSnapshot) -> tuple[bool, str]:
        if not self.is_trading_time(timestamp):
            return False, "outside_trading_window"
        if self.is_news_blackout(timestamp):
            return False, "news_blackout_window"
        if risk.daily_loss_pct >= self.config.max_daily_loss_pct:
            return False, "daily_loss_limit_reached"
        if risk.consecutive_losses >= self.config.max_consecutive_losses:
            return False, "consecutive_loss_limit_reached"
        return True, "ok"

    def is_news_blackout(self, timestamp: pd.Timestamp | datetime) -> bool:
        if not self.news_windows and not self.dynamic_news_windows:
            return False
        local_ts = self.to_local_timestamp(timestamp)
        return any(start <= local_ts < end for start, end in self.news_windows + self.dynamic_news_windows)

    def normalize_direction(self, side: str) -> str:
        return "buy" if side == "buy" else "sell"

    def is_direction_allowed(self, side: str, day_direction: str | None) -> tuple[bool, str]:
        if not self.config.one_direction_per_day:
            return True, "ok"
        if day_direction is None:
            return True, "ok"
        if self.normalize_direction(side) != day_direction:
            return False, "one_direction_per_day"
        return True, "ok"

    def set_dynamic_news_windows(self, windows: list[tuple[pd.Timestamp, pd.Timestamp]]) -> None:
        """注入自动财经日历生成的黑窗。"""
        self.dynamic_news_windows = windows

    @staticmethod
    def _parse_window(value: str) -> tuple[int, int]:
        parts = value.split("-")
        if len(parts) != 2:
            raise ValueError(f"Invalid trading window: {value}")
        return SafetyGuard._parse_time(parts[0]), SafetyGuard._parse_time(parts[1])

    def _parse_news_window(self, value: str) -> tuple[pd.Timestamp, pd.Timestamp]:
        parts = value.split("/")
        if len(parts) != 2:
            raise ValueError(
                "Invalid news blackout window. Use 'YYYY-MM-DD HH:MM/YYYY-MM-DD HH:MM'."
            )
        start = pd.Timestamp(parts[0].strip(), tz=self.timezone)
        end = pd.Timestamp(parts[1].strip(), tz=self.timezone)
        if end <= start:
            raise ValueError(f"Invalid news blackout range: {value}")
        return start, end

    @staticmethod
    def _parse_time(value: str) -> int:
        hour_text, minute_text = value.strip().split(":")
        hour = int(hour_text)
        minute = int(minute_text)
        if hour == 24 and minute == 0:
            return 24 * 60
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError(f"Invalid clock time: {value}")
        return hour * 60 + minute

    @staticmethod
    def _window_contains(start: int, end: int, minute_of_day: int) -> bool:
        if start == end:
            return True
        if start < end:
            return start <= minute_of_day < end
        return minute_of_day >= start or minute_of_day < end
