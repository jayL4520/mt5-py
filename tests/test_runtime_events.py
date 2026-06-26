"""运行时结构化事件的全面测试集。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from mt5_quant.cli import build_parser
from mt5_quant.runtime_events import RuntimeEventFileReader, RuntimeEventWriter, generate_session_id


# ── generate_session_id ────────────────────────────────────────────────

class TestGenerateSessionId:
    def test_returns_string(self) -> None:
        sid = generate_session_id()
        assert isinstance(sid, str)
        assert len(sid) > 10

    def test_contains_timestamp_and_uuid(self) -> None:
        sid = generate_session_id()
        parts = sid.split("-")
        assert len(parts) >= 3

    def test_unique_ids(self) -> None:
        ids = {generate_session_id() for _ in range(100)}
        assert len(ids) == 100


# ── RuntimeEventWriter ─────────────────────────────────────────────────

class TestRuntimeEventWriter:
    def test_writes_jsonl_file(self, tmp_path: Path) -> None:
        writer = RuntimeEventWriter(
            session_id="sid-001",
            symbol="XAUUSD",
            timeframe="M1",
            strategy="xau_m1_momentum",
            timezone_name="Asia/Shanghai",
            base_dir=tmp_path,
        )
        writer.emit(
            "position_opened",
            "已开仓",
            signal_action="buy",
            signal_reason="trend_breakout_long",
            bar_time="2026-05-20 10:00:00",
            position_side="buy",
            extra={"volume": 0.1},
            timestamp=pd.Timestamp("2026-05-20T10:00:00Z"),
        )

        files = list(tmp_path.glob("runtime-events-*.jsonl"))
        assert len(files) == 1
        event = json.loads(files[0].read_text(encoding="utf-8").strip())
        assert event["session_id"] == "sid-001"
        assert event["event_type"] == "position_opened"
        assert event["extra"]["volume"] == 0.1

    def test_multiple_events_appended(self, tmp_path: Path) -> None:
        writer = RuntimeEventWriter(
            session_id="sid-001",
            symbol="XAUUSD",
            timeframe="M1",
            strategy="xau_m1_momentum",
            timezone_name="Asia/Shanghai",
            base_dir=tmp_path,
        )
        writer.emit("event_a", "First", signal_action="buy")
        writer.emit("event_b", "Second", signal_action="sell")

        lines = list(tmp_path.glob("runtime-events-*.jsonl"))[0].read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["event_type"] == "event_a"
        assert json.loads(lines[1])["event_type"] == "event_b"

    def test_event_has_all_required_fields(self, tmp_path: Path) -> None:
        writer = RuntimeEventWriter(
            session_id="sid-002",
            symbol="BTCUSD",
            timeframe="M15",
            strategy="btc_m15_regime",
            timezone_name="Asia/Shanghai",
            base_dir=tmp_path,
        )
        event = writer.emit(
            "signal_blocked",
            "信号被拦截",
            signal_action="buy",
            signal_reason="test",
            blocked_reason="outside_trading_window",
            bar_time="2026-05-20 12:00:00",
            extra={"magic_number": 123},
        )
        assert event["profile"] == ""
        assert event["blocked_reason"] == "outside_trading_window"
        assert event["extra"]["magic_number"] == 123

    def test_filename_based_on_local_date(self, tmp_path: Path) -> None:
        writer = RuntimeEventWriter(
            session_id="sid", symbol="XAUUSD", timeframe="M1",
            strategy="xau_m1_momentum", timezone_name="Asia/Shanghai",
            base_dir=tmp_path,
        )
        writer.emit("test", "msg", timestamp=pd.Timestamp("2026-05-20T10:00:00Z"))
        files = list(tmp_path.glob("runtime-events-2026-05-20.jsonl"))
        assert len(files) == 1

    def test_writer_creates_base_dir(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        writer = RuntimeEventWriter(
            session_id="sid", symbol="XAUUSD", timeframe="M1",
            strategy="xau_m1_momentum", timezone_name="Asia/Shanghai",
            base_dir=nested,
        )
        writer.emit("test", "msg")
        assert nested.exists()

    def test_emit_returns_event_dict(self, tmp_path: Path) -> None:
        writer = RuntimeEventWriter(
            session_id="sid", symbol="XAUUSD", timeframe="M1",
            strategy="xau_m1_momentum", timezone_name="Asia/Shanghai",
            base_dir=tmp_path,
        )
        result = writer.emit("test", "hello", extra={"key": "value"})
        assert isinstance(result, dict)
        assert result["event_type"] == "test"
        assert result["extra"]["key"] == "value"


# ── RuntimeEventFileReader ─────────────────────────────────────────────

class TestRuntimeEventFileReader:
    def test_read_available_empty_when_no_file(self, tmp_path: Path) -> None:
        reader = RuntimeEventFileReader(base_dir=tmp_path)
        events = reader.read_available_events()
        assert events == []

    def test_incremental_read(self, tmp_path: Path) -> None:
        reader = RuntimeEventFileReader(base_dir=tmp_path)
        reader.current_path.write_text(json.dumps({"id": 1}) + "\n", encoding="utf-8")
        first = reader.read_available_events()
        assert len(first) == 1

        with reader.current_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": 2}) + "\n")
        second = reader.read_available_events()
        assert len(second) == 1
        assert second[0]["id"] == 2

    def test_no_new_data_after_consumption(self, tmp_path: Path) -> None:
        reader = RuntimeEventFileReader(base_dir=tmp_path)
        reader.current_path.write_text(json.dumps({"id": 1}) + "\n", encoding="utf-8")
        reader.read_available_events()
        assert reader.read_available_events() == []

    def test_partial_line_buffered(self, tmp_path: Path) -> None:
        reader = RuntimeEventFileReader(base_dir=tmp_path)
        reader.current_path.write_text(
            json.dumps({"id": 1}) + "\n" + '{"id":2',
            encoding="utf-8",
        )
        first = reader.read_available_events()
        assert len(first) == 1

        with reader.current_path.open("a", encoding="utf-8") as f:
            f.write(',"extra":"val"}\n')
        second = reader.read_available_events()
        assert len(second) == 1
        assert second[0]["id"] == 2
        assert second[0]["extra"] == "val"

    def test_load_today_events_reads_all(self, tmp_path: Path) -> None:
        reader = RuntimeEventFileReader(base_dir=tmp_path)
        reader.current_path.write_text(
            json.dumps({"a": 1}) + "\n" + json.dumps({"b": 2}) + "\n",
            encoding="utf-8",
        )
        assert len(reader.load_today_events()) == 2

    def test_malformed_json_skipped(self, tmp_path: Path) -> None:
        reader = RuntimeEventFileReader(base_dir=tmp_path)
        reader.current_path.write_text(
            '{"valid": true}\nnot json\n{"valid": false}\n',
            encoding="utf-8",
        )
        events = reader.load_today_events()
        assert len(events) == 2

    def test_date_change_resets_offset(self, tmp_path: Path) -> None:
        reader = RuntimeEventFileReader(base_dir=tmp_path)
        old_path = tmp_path / "runtime-events-old.jsonl"
        old_path.write_text(json.dumps({"past": True}) + "\n", encoding="utf-8")
        reader.current_path = old_path
        reader.read_available_events()

        new_path = tmp_path / "runtime-events-new.jsonl"
        new_path.write_text(json.dumps({"current": True}) + "\n", encoding="utf-8")
        reader.current_path = new_path
        events = reader.read_available_events()
        assert len(events) == 1
        assert events[0]["current"] is True

    def test_empty_lines_skipped(self, tmp_path: Path) -> None:
        reader = RuntimeEventFileReader(base_dir=tmp_path)
        reader.current_path.write_text('\n\n{"test": true}\n\n', encoding="utf-8")
        assert len(reader.load_today_events()) == 1

    def test_parse_line_invalid_json(self) -> None:
        assert RuntimeEventFileReader._parse_line("not json") is None

    def test_parse_line_not_dict(self) -> None:
        assert RuntimeEventFileReader._parse_line('"just a string"') is None

    def test_parse_line_valid(self) -> None:
        result = RuntimeEventFileReader._parse_line('{"a": 1}')
        assert result == {"a": 1}


# ── CLI session id argument ────────────────────────────────────────────

def test_live_cli_accepts_session_id_argument() -> None:
    parser = build_parser()
    args = parser.parse_args(["live", "--config", "config.xauusd.m1.yaml", "--session-id", "abc123"])
    assert args.session_id == "abc123"

def test_live_cli_default_session_id() -> None:
    parser = build_parser()
    args = parser.parse_args(["live", "--config", "config.xauusd.m1.yaml"])
    assert args.session_id is None
