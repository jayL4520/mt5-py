"""财经日历读取与新闻黑窗生成模块。"""

from __future__ import annotations

import json
import logging
from csv import DictReader
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

from mt5_quant.config import NewsCalendarConfig

LOGGER = logging.getLogger(__name__)
MT5_CALENDAR_CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp936", "gbk")


@dataclass(slots=True)
class NewsBlackoutWindow:
    """单条新闻事件对应的禁开仓时间窗。"""

    start: pd.Timestamp
    end: pd.Timestamp
    title: str
    country: str
    importance: int


class TradingEconomicsCalendarClient:
    """基于 TradingEconomics 官方接口拉取财经日历。"""

    def __init__(self, config: NewsCalendarConfig, timezone_name: str) -> None:
        self.config = config
        self.timezone_name = timezone_name

    def fetch_windows(
        self,
        date_from: datetime | pd.Timestamp,
        date_to: datetime | pd.Timestamp,
    ) -> list[NewsBlackoutWindow]:
        """拉取给定时间区间内的高影响新闻，并转成黑窗。"""
        start = pd.Timestamp(date_from)
        end = pd.Timestamp(date_to)
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        if end.tzinfo is None:
            end = end.tz_localize("UTC")

        events: list[NewsBlackoutWindow] = []
        for country in self.config.countries:
            payload = self._request_events(country, start, end)
            events.extend(self._parse_events(payload))
        return self._deduplicate(events)

    def _request_events(
        self,
        country: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> list[dict[str, object]]:
        """根据时间区间自动选择历史接口或实时快照接口。"""
        now_utc = pd.Timestamp(datetime.now(timezone.utc))
        if start >= now_utc.normalize() - pd.Timedelta(days=1):
            payload = self._request_country_snapshot(country)
            return self._filter_payload_by_time(payload, start, end)
        try:
            return self._request_country_by_date(country, start, end)
        except HTTPError as exc:
            if exc.code != 410:
                raise
            payload = self._request_country_snapshot(country)
            return self._filter_payload_by_time(payload, start, end)

    def _request_country_by_date(
        self,
        country: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> list[dict[str, object]]:
        """按国家和日期区间读取历史财经日历。"""
        country_path = quote(country, safe="")
        start_text = start.tz_convert("UTC").strftime("%Y-%m-%d")
        end_text = end.tz_convert("UTC").strftime("%Y-%m-%d")
        url = (
            f"https://api.tradingeconomics.com/calendar/country/{country_path}/"
            f"{start_text}/{end_text}?c={quote(self.config.api_key, safe=':')}"
            f"&importance={self.config.importance}&f=json"
        )
        request = Request(url, headers={"User-Agent": "mt5-quant-system/0.1"})
        with urlopen(request, timeout=self.config.request_timeout_seconds) as response:
            content = response.read().decode("utf-8")
        payload = json.loads(content)
        if not isinstance(payload, list):
            raise ValueError("Unexpected TradingEconomics payload.")
        return payload

    def _request_country_snapshot(self, country: str) -> list[dict[str, object]]:
        """按国家读取实时快照，用于未来事件过滤。"""
        country_path = quote(country, safe="")
        url = (
            f"https://api.tradingeconomics.com/calendar/country/{country_path}"
            f"?c={quote(self.config.api_key, safe=':')}"
            f"&importance={self.config.importance}&f=json"
        )
        request = Request(url, headers={"User-Agent": "mt5-quant-system/0.1"})
        with urlopen(request, timeout=self.config.request_timeout_seconds) as response:
            content = response.read().decode("utf-8")
        payload = json.loads(content)
        if not isinstance(payload, list):
            raise ValueError("Unexpected TradingEconomics payload.")
        return payload

    def _parse_events(self, payload: list[dict[str, object]]) -> list[NewsBlackoutWindow]:
        """把接口返回转成内部黑窗对象。"""
        windows: list[NewsBlackoutWindow] = []
        for item in payload:
            date_value = item.get("Date")
            if not date_value:
                continue
            event_time = pd.Timestamp(str(date_value))
            if event_time.tzinfo is None:
                event_time = event_time.tz_localize("UTC")
            event_time = event_time.tz_convert(self.timezone_name)
            start = event_time - pd.Timedelta(minutes=self.config.pre_blackout_minutes)
            end = event_time + pd.Timedelta(minutes=self.config.post_blackout_minutes)
            windows.append(
                NewsBlackoutWindow(
                    start=start,
                    end=end,
                    title=str(item.get("Event", "")),
                    country=str(item.get("Country", "")),
                    importance=int(item.get("Importance", self.config.importance) or self.config.importance),
                )
            )
        return windows

    @staticmethod
    def _filter_payload_by_time(
        payload: list[dict[str, object]],
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> list[dict[str, object]]:
        """在本地按时间区间裁剪事件列表。"""
        result: list[dict[str, object]] = []
        for item in payload:
            date_value = item.get("Date")
            if not date_value:
                continue
            event_time = pd.Timestamp(str(date_value))
            if event_time.tzinfo is None:
                event_time = event_time.tz_localize("UTC")
            if start <= event_time.tz_convert("UTC") <= end:
                result.append(item)
        return result

    @staticmethod
    def _deduplicate(windows: list[NewsBlackoutWindow]) -> list[NewsBlackoutWindow]:
        """去重，避免同一事件重复加入黑窗。"""
        result: list[NewsBlackoutWindow] = []
        seen: set[tuple[str, str, str]] = set()
        for window in sorted(windows, key=lambda item: (item.start, item.end, item.title)):
            key = (str(window.start), str(window.end), window.title)
            if key in seen:
                continue
            seen.add(key)
            result.append(window)
        return result


class Mt5FileCalendarClient:
    """读取 MQL5 导出的经济日历 CSV 文件。"""

    def __init__(self, config: NewsCalendarConfig, timezone_name: str, mt5_path: str = "") -> None:
        self.config = config
        self.timezone_name = timezone_name
        self.mt5_path = mt5_path

    def fetch_windows(
        self,
        date_from: datetime | pd.Timestamp,
        date_to: datetime | pd.Timestamp,
    ) -> list[NewsBlackoutWindow]:
        """从 CSV 读取事件并转换为黑窗。"""
        csv_path = self._resolve_csv_path()
        if not csv_path.exists():
            raise FileNotFoundError(f"MT5 calendar export file not found: {csv_path}")

        start = pd.Timestamp(date_from)
        end = pd.Timestamp(date_to)
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        if end.tzinfo is None:
            end = end.tz_localize("UTC")

        windows: list[NewsBlackoutWindow] = []
        with self._open_calendar_csv(csv_path) as handle:
            reader = DictReader(handle)
            for row in reader:
                event_time = pd.Timestamp(str(row.get("utc_time", "")), tz="UTC")
                if event_time < start or event_time > end:
                    continue
                local_time = event_time.tz_convert(self.timezone_name)
                windows.append(
                    NewsBlackoutWindow(
                        start=local_time - pd.Timedelta(minutes=self.config.pre_blackout_minutes),
                        end=local_time + pd.Timedelta(minutes=self.config.post_blackout_minutes),
                        title=str(row.get("title", "")),
                        country=str(row.get("country", "")),
                        importance=int(row.get("importance", self.config.importance) or self.config.importance),
                    )
                )
        return TradingEconomicsCalendarClient._deduplicate(windows)

    @staticmethod
    def _open_calendar_csv(csv_path: Path):
        """按常见 MT5/Windows 编码顺序尝试打开导出的 CSV。"""
        last_error: UnicodeDecodeError | None = None
        for encoding in MT5_CALENDAR_CSV_ENCODINGS:
            handle = None
            try:
                handle = csv_path.open("r", encoding=encoding, newline="")
                handle.read(1)
                handle.seek(0)
                if encoding not in {"utf-8-sig", "utf-8"}:
                    LOGGER.warning("MT5 财经日历文件不是 UTF-8，已自动回退为 %s: %s", encoding, csv_path)
                return handle
            except UnicodeDecodeError as exc:
                last_error = exc
                try:
                    handle.close()
                except Exception:
                    pass

        raise UnicodeDecodeError(
            last_error.encoding if last_error else "unknown",
            last_error.object if last_error else b"",
            last_error.start if last_error else 0,
            last_error.end if last_error else 1,
            (
                f"无法解码 MT5 财经日历文件，请改为 UTF-8 或常见中文 Windows 编码后重试: {csv_path}"
                if last_error is None
                else f"{last_error.reason}；文件路径: {csv_path}"
            ),
        )

    def get_csv_path(self) -> Path:
        """返回当前应读取的 MT5 财经日历导出文件路径。"""
        return self._resolve_csv_path()

    def _resolve_csv_path(self) -> Path:
        """优先使用显式 file_path，否则自动定位 MT5 Common\\Files。"""
        if self.config.file_path:
            return Path(self.config.file_path)

        try:
            import MetaTrader5 as mt5
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("MetaTrader5 package is required for mt5_file calendar provider.") from exc

        initialized_here = False
        if mt5.terminal_info() is None:
            if self.mt5_path:
                initialized_here = mt5.initialize(path=self.mt5_path)
            else:
                initialized_here = mt5.initialize()
            if not initialized_here:
                code, message = mt5.last_error()
                raise RuntimeError(f"MT5 initialize failed while resolving common file path: {code} {message}")

        try:
            info = mt5.terminal_info()
            if info is None:
                raise RuntimeError("Failed to read MT5 terminal_info().")
            return Path(info.commondata_path) / "Files" / self.config.common_filename
        finally:
            if initialized_here:
                mt5.shutdown()


def build_calendar_client(
    config: NewsCalendarConfig,
    timezone_name: str,
    mt5_path: str = "",
) -> TradingEconomicsCalendarClient | Mt5FileCalendarClient | None:
    """根据配置构造财经日历客户端。"""
    if not config.enabled or config.provider == "disabled":
        return None
    if config.provider == "mt5_file":
        return Mt5FileCalendarClient(config, timezone_name, mt5_path)
    if config.provider == "tradingeconomics":
        return TradingEconomicsCalendarClient(config, timezone_name)
    LOGGER.warning("Unsupported calendar provider: %s", config.provider)
    return None


def validate_calendar_data_source(
    config: NewsCalendarConfig,
    timezone_name: str,
    mt5_path: str = "",
) -> Path | None:
    """在启动交易或回测前校验财经日历数据源是否就绪。"""
    client = build_calendar_client(config, timezone_name, mt5_path)
    if client is None:
        return None

    if isinstance(client, Mt5FileCalendarClient):
        csv_path = client.get_csv_path()
        if not csv_path.exists():
            raise FileNotFoundError(
                "已启用 MT5 财经日历文件模式，但未找到新闻文件："
                f"{csv_path}\n"
                "请先在 MT5 中挂载并运行 mql5/ExportEconomicCalendar.mq5，"
                "确认已导出 Common\\Files\\mt5_calendar_events.csv 后再启动。"
            )
        return csv_path

    return None
