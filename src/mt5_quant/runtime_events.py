"""运行期结构化事件写入与读取。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from mt5_quant.launcher_profiles import get_logs_dir


EVENT_FILE_PREFIX = "runtime-events-"


def generate_session_id() -> str:
    """生成本次运行会话 ID。"""
    return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"


class RuntimeEventWriter:
    """按日期输出 JSONL 运行事件。"""

    def __init__(
        self,
        session_id: str,
        symbol: str,
        timeframe: str,
        strategy: str,
        timezone_name: str,
        profile: str = "",
        base_dir: Path | None = None,
    ) -> None:
        self.session_id = session_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.strategy = strategy
        self.timezone = ZoneInfo(timezone_name)
        self.profile = profile
        self.base_dir = base_dir or get_logs_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        event_type: str,
        message: str,
        *,
        signal_action: str = "",
        signal_reason: str = "",
        blocked_reason: str = "",
        bar_time: str = "",
        position_side: str = "",
        extra: dict[str, object] | None = None,
        timestamp: pd.Timestamp | datetime | None = None,
    ) -> dict[str, object]:
        """追加写入一条结构化事件。"""
        event_ts = pd.Timestamp(timestamp or datetime.utcnow())
        if event_ts.tzinfo is None:
            event_ts = event_ts.tz_localize("UTC")
        else:
            event_ts = event_ts.tz_convert("UTC")
        event = {
            "timestamp": str(event_ts),
            "session_id": self.session_id,
            "profile": self.profile,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "strategy": self.strategy,
            "event_type": event_type,
            "message": message,
            "signal_action": signal_action,
            "signal_reason": signal_reason,
            "blocked_reason": blocked_reason,
            "bar_time": bar_time,
            "position_side": position_side,
            "extra": extra or {},
        }
        file_path = self._resolve_file_path(event_ts)
        with file_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def _resolve_file_path(self, timestamp: pd.Timestamp) -> Path:
        local_date = timestamp.tz_convert(self.timezone).strftime("%Y-%m-%d")
        return self.base_dir / f"{EVENT_FILE_PREFIX}{local_date}.jsonl"


class RuntimeEventFileReader:
    """按日读取并增量跟踪运行事件文件。"""

    def __init__(self, timezone_name: str = "Asia/Shanghai", base_dir: Path | None = None) -> None:
        self.timezone = ZoneInfo(timezone_name)
        self.base_dir = base_dir or get_logs_dir()
        self.offset = 0
        self.partial_line = ""
        self.current_path = self._resolve_current_path()

    def read_available_events(self) -> list[dict[str, object]]:
        """读取当前日期文件中尚未读取的新事件。"""
        path = self._resolve_current_path()
        if path != self.current_path:
            self.current_path = path
            self.offset = 0
            self.partial_line = ""
        if not path.exists():
            return []

        with path.open("r", encoding="utf-8") as handle:
            handle.seek(self.offset)
            chunk = handle.read()
            self.offset = handle.tell()

        if not chunk and not self.partial_line:
            return []

        text = self.partial_line + chunk
        lines = text.splitlines(keepends=True)
        if lines and not lines[-1].endswith("\n"):
            self.partial_line = lines.pop()
        else:
            self.partial_line = ""

        events: list[dict[str, object]] = []
        for line in lines:
            parsed = self._parse_line(line)
            if parsed is not None:
                events.append(parsed)
        return events

    def load_today_events(self) -> list[dict[str, object]]:
        """一次性加载当天全部有效事件。"""
        self.current_path = self._resolve_current_path()
        self.offset = 0
        self.partial_line = ""
        return self.read_available_events()

    def _resolve_current_path(self) -> Path:
        current_date = datetime.now(self.timezone).strftime("%Y-%m-%d")
        return self.base_dir / f"{EVENT_FILE_PREFIX}{current_date}.jsonl"

    @staticmethod
    def _parse_line(line: str) -> dict[str, object] | None:
        content = line.strip()
        if not content:
            return None
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
