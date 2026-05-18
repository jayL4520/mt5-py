"""运行前校验与优化模板的最小测试集。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mt5_quant.config import NewsCalendarConfig
from mt5_quant.diagnostics import summarize_diagnosis
from mt5_quant.news_calendar import validate_calendar_data_source
from mt5_quant.optimizer import build_parameter_grid, resolve_worker_count


def test_validate_calendar_data_source_raises_when_mt5_file_missing(tmp_path: Path) -> None:
    config = NewsCalendarConfig(
        enabled=True,
        provider="mt5_file",
        api_key="guest:guest",
        countries=["united states"],
        importance=3,
        pre_blackout_minutes=10,
        post_blackout_minutes=10,
        lookahead_days=7,
        cache_minutes=30,
        request_timeout_seconds=20,
        common_filename="mt5_calendar_events.csv",
        file_path=str(tmp_path / "missing_calendar.csv"),
    )

    with pytest.raises(FileNotFoundError, match="未找到新闻文件"):
        validate_calendar_data_source(config, "Asia/Shanghai", "")


def test_build_parameter_grid_expands_all_combinations() -> None:
    grid = build_parameter_grid(
        {
            "ema_fast": [18, 20],
            "ema_slow": [55, 60],
            "adx_threshold": [20],
        }
    )

    assert len(grid) == 4
    assert {"ema_fast": 18, "ema_slow": 55, "adx_threshold": 20} in grid
    assert {"ema_fast": 20, "ema_slow": 60, "adx_threshold": 20} in grid


def test_resolve_worker_count_respects_bounds() -> None:
    assert resolve_worker_count(None, 1) == 1
    assert resolve_worker_count(16, 3) == 3
    assert resolve_worker_count(0, 5) == 1


def test_summarize_diagnosis_reports_interval_mismatch() -> None:
    data = load_sample_frame(
        [
            "2026-05-18T00:00:00Z",
            "2026-05-18T00:01:00Z",
            "2026-05-18T00:02:00Z",
        ]
    )
    raw_scan = {
        "raw_action_counts": {"hold": 3},
        "raw_reason_counts": {"no_signal": 3},
        "raw_entry_signal_count": 0,
        "recent_entry_signals": [],
    }
    backtest_summary = {
        "final_balance": 100000.0,
        "net_profit": 0.0,
        "total_trades": 0,
        "win_rate": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "avg_trade": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "profit_factor": 0.0,
        "max_drawdown_pct": 0.0,
        "blocked_entries": {},
    }
    calendar_info = {"calendar_status": "ok", "calendar_message": "calendar.csv"}

    summary = summarize_diagnosis(
        config=load_runtime_config("config.btcusd.m15.offline.yaml"),
        data=data,
        raw_scan=raw_scan,
        backtest_summary=backtest_summary,
        calendar_info=calendar_info,
    )

    assert summary["actual_interval_minutes"] == 1.0
    assert summary["expected_interval_minutes"] == 15
    assert summary["interval_matches_config"] is False
    assert any("样本周期与配置不匹配" in item for item in summary["diagnosis_conclusions"])


def load_runtime_config(path: str):
    from mt5_quant.config import load_config

    return load_config(path)


def load_sample_frame(times: list[str]):
    import pandas as pd

    frame = pd.DataFrame(
        {
            "time": times,
            "open": [1.0] * len(times),
            "high": [1.1] * len(times),
            "low": [0.9] * len(times),
            "close": [1.0] * len(times),
        }
    )
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time")
