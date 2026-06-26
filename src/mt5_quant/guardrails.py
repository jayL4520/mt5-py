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
        if risk.consecutive_losses > self.config.max_consecutive_losses:
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
    
# ── 强化熔断：阶梯式冷却机制 ─────────────────────────────────────────
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Literal


CoolingMode = Literal["normal", "cooldown_15m", "cooldown_1h", "close_only"]


class LossStreakGuardrail:
    """阶梯式熔断系统。

    - ≥3 连亏：PAUSE 15 分钟
    - ≥5 连亏：CLOSE_ONLY 1 小时
    - ≥7 连亏：ALERT + 保存行情片段

    状态持久化：~/.mt5_py/state/{symbol}_{timeframe}.cooling.json
    """

    STATE_DIR = Path.home() / ".mt5_py" / "state"

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        max_streak_3: int = 3,
        max_streak_5: int = 5,
        max_streak_7: int = 7,
        cooldown_15m_minutes: int = 15,
        cooldown_1h_minutes: int = 60,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.max_streak_3 = max_streak_3
        self.max_streak_5 = max_streak_5
        self.max_streak_7 = max_streak_7
        self.cooldown_15m = cooldown_15m_minutes * 60
        self.cooldown_1h = cooldown_1h_minutes * 60

        # Runtime state
        self.loss_streak: int = 0
        self.mode: CoolingMode = "normal"
        self.cooldown_until: float = 0.0

        # Callbacks
        self._alert_callback = None

        # Load persisted state
        self._load_state()

    def set_alert_callback(self, callback) -> None:
        """设置警报回调函数（用于接 Telegram / 邮件）。"""
        self._alert_callback = callback

    def on_trade_result(self, is_profit: bool, extra_info: str = "") -> None:
        """每次平仓后调用。"""
        if is_profit:
            self.loss_streak = 0
            self._log("Profit! Reset loss streak.")
        else:
            self.loss_streak += 1
            self._log(f"Loss #{self.loss_streak}")

            if self.loss_streak >= self.max_streak_7:
                self.mode = "close_only"
                self.cooldown_until = time.time() + self.cooldown_1h
                msg = (
                    f"🚨 {self.loss_streak}连亏！进入仅平仓模式1小时，"
                    f"至 {datetime.fromtimestamp(self.cooldown_until).strftime('%H:%M:%S')}"
                )
                self._alert(msg, extra_info)
            elif self.loss_streak >= self.max_streak_5:
                self.mode = "cooldown_1h"
                self.cooldown_until = time.time() + self.cooldown_1h
                self._log(f"⚠️ {self.loss_streak}连亏，暂停1小时")
            elif self.loss_streak >= self.max_streak_3:
                self.mode = "cooldown_15m"
                self.cooldown_until = time.time() + self.cooldown_15m
                self._log(f"⚠️ {self.loss_streak}连亏，暂停15分钟")

        self._save_state()

    def can_trade(self) -> bool:
        """检查当前是否允许开新仓。"""
        if self.mode == "normal":
            return True
            
        if self.cooldown_until and time.time() > self.cooldown_until:
            self.mode = "normal"
            self.cooldown_until = 0.0
            self._log("✅ 冷却结束，恢复交易")
            self._save_state()
            return True
            
        return False

    def can_close_only(self) -> bool:
        """检查是否只允许平仓（close_only 模式）。"""
        return self.mode == "close_only"

    def get_status(self) -> dict:
        """返回当前熔断状态（可用于前端展示）。"""
        remaining = max(0.0, self.cooldown_until - time.time()) if self.cooldown_until > 0 else 0.0
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "loss_streak": self.loss_streak,
            "mode": self.mode,
            "cooldown_remaining_seconds": int(remaining),
            "can_trade": self.can_trade(),
        }

    def _state_file(self) -> Path:
        self.STATE_DIR.mkdir(parents=True, exist_ok=True)
        return self.STATE_DIR / f"{self.symbol}_{self.timeframe}.cooling.json"

    def _save_state(self) -> None:
        path = self._state_file()
        try:
            path.write_text(
                json.dumps(
                    {
                        "loss_streak": self.loss_streak,
                        "mode": self.mode,
                        "cooldown_until": self.cooldown_until,
                        "updated_at": time.time(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            self._log(f"保存熔断状态失败: {exc}")

    def _load_state(self) -> None:
        path = self._state_file()
        if not path.exists():
            return
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            self.loss_streak = int(state.get("loss_streak", 0))
            self.mode = state.get("mode", "normal")
            self.cooldown_until = float(state.get("cooldown_until", 0.0))

            # 如果冷却已过期，自动恢复
            if self.cooldown_until > 0 and time.time() > self.cooldown_until:
                self.mode = "normal"
                self.cooldown_until = 0.0
                self.loss_streak = 0
                self._log("重启后冷却已过期，自动恢复交易")
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            self._log(f"读取熔断状态失败，使用默认值: {exc}")
            self.loss_streak = 0
            self.mode = "normal"
            self.cooldown_until = 0.0

    def _log(self, msg: str) -> None:
        print(f"[GUARDRAIL] {msg}")

    def _alert(self, msg: str, extra_info: str = "") -> None:
        if self._alert_callback:
            self._alert_callback(msg, extra_info)
        else:
            print(f"[ALERT] {msg}")