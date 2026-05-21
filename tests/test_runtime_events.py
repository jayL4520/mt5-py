"""运行时结构化事件的最小测试集。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from mt5_quant.cli import build_parser
from mt5_quant.runtime_events import RuntimeEventFileReader, RuntimeEventWriter


def test_runtime_event_writer_outputs_jsonl(tmp_path: Path) -> None:
    writer = RuntimeEventWriter(
        session_id="session-123",
        symbol="XAUUSD",
        timeframe="M1",
        strategy="xau_m1_momentum",
        timezone_name="Asia/Shanghai",
        base_dir=tmp_path,
    )

    writer.emit(
        "signal_blocked",
        "信号被拦截：不在允许交易时段内",
        signal_action="buy",
        signal_reason="trend_breakout_long",
        blocked_reason="outside_trading_window",
        bar_time="2026-05-19 01:00:00+00:00",
        extra={"daily_loss_pct": 0.0},
        timestamp=pd.Timestamp("2026-05-19T01:00:00Z"),
    )

    files = list(tmp_path.glob("runtime-events-*.jsonl"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert payload["session_id"] == "session-123"
    assert payload["event_type"] == "signal_blocked"
    assert payload["blocked_reason"] == "outside_trading_window"
    assert payload["symbol"] == "XAUUSD"


def test_runtime_event_reader_loads_history_and_tolerates_partial_lines(tmp_path: Path) -> None:
    reader = RuntimeEventFileReader(base_dir=tmp_path)
    reader.current_path.write_text(
        json.dumps({"session_id": "s1", "event_type": "signal_hold", "message": "ok"}, ensure_ascii=False) + "\n"
        + '{"session_id":"s2","event_type":"runtime_error"',
        encoding="utf-8",
    )

    initial = reader.load_today_events()
    assert len(initial) == 1
    assert initial[0]["session_id"] == "s1"

    with reader.current_path.open("a", encoding="utf-8") as handle:
        handle.write(',"message":"补全"}\n')

    incremental = reader.read_available_events()
    assert len(incremental) == 1
    assert incremental[0]["session_id"] == "s2"
    assert incremental[0]["event_type"] == "runtime_error"


def test_live_cli_accepts_session_id_argument() -> None:
    parser = build_parser()
    args = parser.parse_args(["live", "--config", "config.xauusd.m1.yaml", "--session-id", "abc123"])
    assert args.session_id == "abc123"
