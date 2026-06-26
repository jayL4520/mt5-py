"""单元测试：news_calendar — 财经日历与新闻黑窗。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from mt5_quant.config import NewsCalendarConfig
from mt5_quant.news_calendar import (
    Mt5FileCalendarClient,
    NewsBlackoutWindow,
    TradingEconomicsCalendarClient,
    build_calendar_client,
    validate_calendar_data_source,
)


# ── NewsBlackoutWindow ──────────────────────────────────────────────────

class TestNewsBlackoutWindow:
    def test_full_window(self) -> None:
        w = NewsBlackoutWindow(
            start=pd.Timestamp("2026-05-20 14:00", tz="Asia/Shanghai"),
            end=pd.Timestamp("2026-05-20 14:10", tz="Asia/Shanghai"),
            title="FOMC",
            country="United States",
            importance=3,
        )
        assert w.title == "FOMC"
        assert w.importance == 3
        assert w.start < w.end


# ── build_calendar_client ───────────────────────────────────────────────

class TestBuildCalendarClient:
    def test_disabled_returns_none(self) -> None:
        config = NewsCalendarConfig(
            enabled=False, provider="disabled", api_key="",
            countries=[], importance=3, pre_blackout_minutes=10, post_blackout_minutes=10,
            lookahead_days=7, cache_minutes=30, request_timeout_seconds=20,
            common_filename="", file_path="",
        )
        client = build_calendar_client(config, "Asia/Shanghai")
        assert client is None

    def test_unsupported_provider_returns_none(self) -> None:
        config = NewsCalendarConfig(
            enabled=False, provider="unknown", api_key="",
            countries=[], importance=3, pre_blackout_minutes=10, post_blackout_minutes=10,
            lookahead_days=7, cache_minutes=30, request_timeout_seconds=20,
            common_filename="", file_path="",
        )
        client = build_calendar_client(config, "Asia/Shanghai")
        assert client is None

    def test_mt5_file_client_created(self) -> None:
        config = NewsCalendarConfig(
            enabled=True, provider="mt5_file", api_key="",
            countries=["united states"], importance=3,
            pre_blackout_minutes=10, post_blackout_minutes=10,
            lookahead_days=7, cache_minutes=30, request_timeout_seconds=20,
            common_filename="mt5_calendar_events.csv", file_path="",
        )
        client = build_calendar_client(config, "Asia/Shanghai")
        assert isinstance(client, Mt5FileCalendarClient)

    def test_tradingeconomics_client_created(self) -> None:
        config = NewsCalendarConfig(
            enabled=True, provider="tradingeconomics", api_key="guest:guest",
            countries=["united states"], importance=3,
            pre_blackout_minutes=10, post_blackout_minutes=10,
            lookahead_days=7, cache_minutes=30, request_timeout_seconds=20,
            common_filename="", file_path="",
        )
        client = build_calendar_client(config, "Asia/Shanghai")
        assert isinstance(client, TradingEconomicsCalendarClient)


# ── Mt5FileCalendarClient ──────────────────────────────────────────────

class TestMt5FileCalendarClient:
    def test_read_csv_with_utf8_bom(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "events.csv"
        csv_path.write_bytes(
            b"\xef\xbb\xbfutc_time,title,country,importance\n"
            b"2026-05-20 12:30:00,FOMC,United States,3\n"
            b"2026-05-20 14:00:00,GDP,United States,3\n"
        )
        config = NewsCalendarConfig(
            enabled=True, provider="mt5_file", api_key="",
            countries=[], importance=3, pre_blackout_minutes=10,
            post_blackout_minutes=10, lookahead_days=7, cache_minutes=30,
            request_timeout_seconds=20, common_filename="events.csv",
            file_path=str(csv_path),
        )
        client = Mt5FileCalendarClient(config, "Asia/Shanghai")
        windows = client.fetch_windows(
            pd.Timestamp("2026-05-20 00:00", tz="UTC"),
            pd.Timestamp("2026-05-21 00:00", tz="UTC"),
        )
        assert len(windows) == 2
        assert windows[0].title == "FOMC"

    def test_read_csv_with_gbk(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "events.csv"
        csv_path.write_text(
            "utc_time,title,country,importance\n"
            "2026-05-20 12:30:00,美元数据,United States,3\n",
            encoding="gbk",
        )
        config = NewsCalendarConfig(
            enabled=True, provider="mt5_file", api_key="",
            countries=[], importance=3, pre_blackout_minutes=10,
            post_blackout_minutes=10, lookahead_days=7, cache_minutes=30,
            request_timeout_seconds=20, common_filename="events.csv",
            file_path=str(csv_path),
        )
        client = Mt5FileCalendarClient(config, "Asia/Shanghai")
        windows = client.fetch_windows(
            pd.Timestamp("2026-05-20 00:00", tz="UTC"),
            pd.Timestamp("2026-05-21 00:00", tz="UTC"),
        )
        assert len(windows) == 1
        assert windows[0].title == "美元数据"

    def test_csv_file_not_found(self, tmp_path: Path) -> None:
        config = NewsCalendarConfig(
            enabled=True, provider="mt5_file", api_key="",
            countries=[], importance=3, pre_blackout_minutes=10,
            post_blackout_minutes=10, lookahead_days=7, cache_minutes=30,
            request_timeout_seconds=20, common_filename="events.csv",
            file_path=str(tmp_path / "nonexistent.csv"),
        )
        client = Mt5FileCalendarClient(config, "Asia/Shanghai")
        with pytest.raises(FileNotFoundError, match="MT5 calendar export file not found"):
            client.fetch_windows(
                pd.Timestamp("2026-05-20 00:00", tz="UTC"),
                pd.Timestamp("2026-05-21 00:00", tz="UTC"),
            )

    def test_filter_events_by_date_range(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "events.csv"
        csv_path.write_text(
            "utc_time,title,country,importance\n"
            "2026-05-19 12:00:00,Old Event,US,3\n"
            "2026-05-20 12:00:00,FOMC,US,3\n"
            "2026-05-21 12:00:00,Future Event,US,3\n",
        )
        config = NewsCalendarConfig(
            enabled=True, provider="mt5_file", api_key="",
            countries=[], importance=3, pre_blackout_minutes=10,
            post_blackout_minutes=10, lookahead_days=7, cache_minutes=30,
            request_timeout_seconds=20, common_filename="events.csv",
            file_path=str(csv_path),
        )
        client = Mt5FileCalendarClient(config, "Asia/Shanghai")
        windows = client.fetch_windows(
            pd.Timestamp("2026-05-20 00:00", tz="UTC"),
            pd.Timestamp("2026-05-20 23:59", tz="UTC"),
        )
        assert len(windows) == 1
        assert windows[0].title == "FOMC"

    def test_blackout_minutes_applied(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "events.csv"
        csv_path.write_text(
            "utc_time,title,country,importance\n"
            "2026-05-20 12:00:00,FOMC,US,3\n",
        )
        config = NewsCalendarConfig(
            enabled=True, provider="mt5_file", api_key="",
            countries=[], importance=3, pre_blackout_minutes=30,
            post_blackout_minutes=15, lookahead_days=7, cache_minutes=30,
            request_timeout_seconds=20, common_filename="events.csv",
            file_path=str(csv_path),
        )
        client = Mt5FileCalendarClient(config, "Asia/Shanghai")
        windows = client.fetch_windows(
            pd.Timestamp("2026-05-20 00:00", tz="UTC"),
            pd.Timestamp("2026-05-21 00:00", tz="UTC"),
        )
        assert len(windows) == 1
        # Event at UTC 12:00, converted to Shanghai 20:00
        # Blackout: 19:30 - 20:15 Shanghai time
        local_start = windows[0].start
        local_end = windows[0].end
        assert local_start.hour == 19
        assert local_start.minute == 30
        assert local_end.hour == 20
        assert local_end.minute == 15

    def test_get_csv_path_uses_file_path(self, tmp_path: Path) -> None:
        file_path = tmp_path / "custom_events.csv"
        file_path.write_text("utc_time,title\n", encoding="utf-8")
        config = NewsCalendarConfig(
            enabled=True, provider="mt5_file", api_key="",
            countries=[], importance=3, pre_blackout_minutes=10,
            post_blackout_minutes=10, lookahead_days=7, cache_minutes=30,
            request_timeout_seconds=20, common_filename="events.csv",
            file_path=str(file_path),
        )
        client = Mt5FileCalendarClient(config, "Asia/Shanghai")
        assert client.get_csv_path() == file_path

    def test_validate_mt5_file_missing_raises(self, tmp_path: Path) -> None:
        config = NewsCalendarConfig(
            enabled=True, provider="mt5_file", api_key="",
            countries=[], importance=3, pre_blackout_minutes=10,
            post_blackout_minutes=10, lookahead_days=7, cache_minutes=30,
            request_timeout_seconds=20, common_filename="events.csv",
            file_path=str(tmp_path / "nonexistent.csv"),
        )
        with pytest.raises(FileNotFoundError, match="未找到新闻文件"):
            validate_calendar_data_source(config, "Asia/Shanghai", "")

    def test_validate_disabled_returns_none(self) -> None:
        config = NewsCalendarConfig(
            enabled=False, provider="disabled", api_key="",
            countries=[], importance=3, pre_blackout_minutes=10,
            post_blackout_minutes=10, lookahead_days=7, cache_minutes=30,
            request_timeout_seconds=20, common_filename="", file_path="",
        )
        result = validate_calendar_data_source(config, "Asia/Shanghai", "")
        assert result is None


# ── TradingEconomicsCalendarClient ──────────────────────────────────────

class TestTradingEconomicsCalendarClient:
    def test_deduplicate_removes_duplicates(self) -> None:
        windows = [
            NewsBlackoutWindow(
                start=pd.Timestamp("2026-05-20 14:00", tz="UTC"),
                end=pd.Timestamp("2026-05-20 14:10", tz="UTC"),
                title="FOMC", country="US", importance=3,
            ),
            NewsBlackoutWindow(
                start=pd.Timestamp("2026-05-20 14:00", tz="UTC"),
                end=pd.Timestamp("2026-05-20 14:10", tz="UTC"),
                title="FOMC", country="US", importance=3,
            ),
            NewsBlackoutWindow(
                start=pd.Timestamp("2026-05-20 15:00", tz="UTC"),
                end=pd.Timestamp("2026-05-20 15:10", tz="UTC"),
                title="GDP", country="US", importance=2,
            ),
        ]
        deduped = TradingEconomicsCalendarClient._deduplicate(windows)
        assert len(deduped) == 2

    def test_filter_payload_by_time(self) -> None:
        payload = [
            {"Date": "2026-05-20T12:00:00", "Event": "FOMC"},
            {"Date": "2026-05-21T12:00:00", "Event": "GDP"},
        ]
        filtered = TradingEconomicsCalendarClient._filter_payload_by_time(
            payload,
            pd.Timestamp("2026-05-20T00:00:00Z"),
            pd.Timestamp("2026-05-20T23:59:59Z"),
        )
        assert len(filtered) == 1
        assert filtered[0]["Event"] == "FOMC"

    def test_parse_events_with_pre_post_blackout(self) -> None:
        """Verify pre/post_blackout_minutes are applied correctly."""
        config = NewsCalendarConfig(
            enabled=True, provider="tradingeconomics", api_key="guest:guest",
            countries=["united states"], importance=3,
            pre_blackout_minutes=15, post_blackout_minutes=5,
            lookahead_days=7, cache_minutes=30, request_timeout_seconds=20,
            common_filename="", file_path="",
        )
        client = TradingEconomicsCalendarClient(config, "Asia/Shanghai")
        payload = [
            {"Date": "2026-05-20T12:00:00", "Event": "FOMC", "Country": "United States", "Importance": "3"},
        ]
        windows = client._parse_events(payload)
        assert len(windows) == 1
        w = windows[0]
        # Event at UTC 12:00 = Shanghai 20:00
        # Start = 19:45, End = 20:05
        assert w.start.hour == 19
        assert w.start.minute == 45
        assert w.end.hour == 20
        assert w.end.minute == 5

    def test_parse_events_skips_missing_date(self) -> None:
        config = NewsCalendarConfig(
            enabled=True, provider="tradingeconomics", api_key="guest:guest",
            countries=[], importance=3,
            pre_blackout_minutes=10, post_blackout_minutes=10,
            lookahead_days=7, cache_minutes=30, request_timeout_seconds=20,
            common_filename="", file_path="",
        )
        client = TradingEconomicsCalendarClient(config, "Asia/Shanghai")
        payload = [{"Event": "NoDate"}]
        windows = client._parse_events(payload)
        assert len(windows) == 0
