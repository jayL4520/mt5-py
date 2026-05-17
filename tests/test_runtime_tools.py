"""运行前校验与优化模板的最小测试集。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mt5_quant.config import NewsCalendarConfig
from mt5_quant.news_calendar import validate_calendar_data_source
from mt5_quant.optimizer import build_parameter_grid


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
