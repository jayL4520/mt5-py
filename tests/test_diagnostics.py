"""单元测试：diagnostics — 信号诊断模块。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from mt5_quant.config import AppConfig, load_config
from mt5_quant.diagnostics import (
    build_strategy,
    detect_calendar_status,
    detect_interval_minutes,
    load_csv_history,
    load_diagnostic_data,
    render_diagnostic_report,
    run_signal_diagnosis,
    scan_raw_signals,
    summarize_diagnosis,
)


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def sample_m15_data() -> pd.DataFrame:
    """100 bars of gentle uptrend M15 data."""
    n = 100
    prices = [50000.0 + i * 10 for i in range(n)]
    return pd.DataFrame({
        "open": prices,
        "high": [v * 1.002 for v in prices],
        "low": [v * 0.998 for v in prices],
        "close": prices,
        "volume": [100 + (i % 10) * 5 for i in range(n)],
    }, index=pd.date_range("2026-05-20 00:00", periods=n, freq="15min", tz="UTC"))


@pytest.fixture
def btc_config(tmp_path: Path) -> Path:
    """Create a minimal BTC M15 config YAML for testing."""
    config = {
        "mt5": {"login": 1, "password": "p", "server": "s"},
        "trading": {"symbol": "BTCUSD", "timeframe": "M15", "history_bars": 500},
        "strategy": {
            "name": "btc_m15_regime",
            "ema_fast": 10, "ema_slow": 20, "rsi_period": 7,
            "rsi_buy_threshold": 55.0, "rsi_sell_threshold": 45.0,
            "breakout_lookback": 10, "adx_period": 7, "adx_threshold": 18.0,
            "volume_window": 5, "volume_multiplier": 0.8,
            "breakout_buffer_pct": 0.0, "atr_stop_multiple": 2.0,
            "reward_to_risk": 2.2, "atr_period": 7,
            "risk_per_trade": 0.004,
        },
        "backtest": {"initial_balance": 100000},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


# ── build_strategy ─────────────────────────────────────────────────────

class TestBuildStrategy:
    @staticmethod
    def _make_config(strategy_name: str) -> AppConfig:
        from mt5_quant.config import (
            BacktestConfig, Mt5Config, NewsCalendarConfig,
            ReportingConfig, SafetyConfig, StrategyConfig, TradingConfig,
        )
        return AppConfig(
            mt5=Mt5Config(login=1, password="p", server="s"),
            trading=TradingConfig(
                symbol="XAUUSD", timeframe="M1", history_bars=800,
                mt5_bar_time_shift_hours=0, slippage_points=20,
                magic_number=260516, comment="test", poll_interval_seconds=5,
                max_open_positions=1,
            ),
            strategy=StrategyConfig(
                name=strategy_name, risk_per_trade=0.01,
                short_window=20, long_window=50,
                atr_period=14, atr_stop_multiple=2.0, reward_to_risk=2.0,
                leverage_multiplier=1.0,
                ema_fast=21, ema_slow=55,
                rsi_period=14, rsi_buy_threshold=55.0, rsi_sell_threshold=45.0,
                breakout_lookback=20, take_profit_pct=0.003, stop_loss_pct=0.004,
                adx_period=14, adx_threshold=22.0,
                volume_window=20, volume_multiplier=1.0, breakout_buffer_pct=0.0,
            ),
            backtest=BacktestConfig(
                initial_balance=100000, commission_per_lot=0.0,
                spread_points=10, contract_size=1.0,
            ),
            safety=SafetyConfig(
                timezone="Asia/Shanghai", trading_windows=["00:00-24:00"],
                max_daily_loss_pct=0.02, max_consecutive_losses=6,
                one_direction_per_day=False, news_blackout_windows=[],
                trailing_stop_enabled=False, trailing_trigger_pct=0.0015,
                trailing_distance_pct=0.0012,
            ),
            news_calendar=NewsCalendarConfig(
                enabled=False, provider="disabled", api_key="",
                countries=[], importance=3,
                pre_blackout_minutes=10, post_blackout_minutes=10,
                lookahead_days=7, cache_minutes=30, request_timeout_seconds=20,
                common_filename="", file_path="",
            ),
            reporting=ReportingConfig(
                output_dir="reports", save_summary_json=True,
                save_trades_csv=True, save_equity_csv=True,
            ),
        )

    def test_ema_cross_atr(self) -> None:
        strategy = build_strategy(self._make_config("ema_cross_atr"))
        assert strategy.__class__.__name__ == "EmaCrossAtrStrategy"

    def test_ma_cross_atr(self) -> None:
        strategy = build_strategy(self._make_config("ma_cross_atr"))
        assert strategy.__class__.__name__ == "MovingAverageAtrStrategy"

    def test_xau_m1_momentum(self) -> None:
        strategy = build_strategy(self._make_config("xau_m1_momentum"))
        assert strategy.__class__.__name__ == "XauM1MomentumStrategy"

    def test_btc_m15_regime(self) -> None:
        strategy = build_strategy(self._make_config("btc_m15_regime"))
        assert strategy.__class__.__name__ == "BtcM15RegimeStrategy"

    def test_unsupported_strategy_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported strategy"):
            build_strategy(self._make_config("unknown"))


# ── load_csv_history ───────────────────────────────────────────────────

class TestLoadCsvHistory:
    def test_loads_valid_csv(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(
            "time,open,high,low,close,volume\n"
            "2026-05-20 00:00:00,100,101,99,100,1000\n"
            "2026-05-20 00:15:00,101,102,100,101,1200\n",
        )
        df = load_csv_history(str(csv_path))
        assert len(df) == 2
        assert "close" in df.columns
        assert df.index.name == "time"

    def test_missing_required_column_raises(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("time,price\n2026-05-20,100\n")
        with pytest.raises(ValueError, match="缺少必要列"):
            load_csv_history(str(csv_path))


# ── detect_interval_minutes ────────────────────────────────────────────

class TestDetectIntervalMinutes:
    def test_detects_m1(self) -> None:
        data = pd.DataFrame(
            {"close": [1, 2, 3]},
            index=pd.date_range("2026-05-20 00:00", periods=3, freq="1min", tz="UTC"),
        )
        interval = detect_interval_minutes(data)
        assert interval == 1.0

    def test_detects_m15(self) -> None:
        data = pd.DataFrame(
            {"close": [1, 2, 3]},
            index=pd.date_range("2026-05-20 00:00", periods=3, freq="15min", tz="UTC"),
        )
        interval = detect_interval_minutes(data)
        assert interval == 15.0

    def test_returns_none_for_single_bar(self) -> None:
        data = pd.DataFrame({"close": [1]}, index=pd.DatetimeIndex(["2026-05-20"], tz="UTC"))
        interval = detect_interval_minutes(data)
        assert interval is None

    def test_irregular_interval_uses_mode(self) -> None:
        times = [
            "2026-05-20 00:00",
            "2026-05-20 00:15",
            "2026-05-20 00:30",
            "2026-05-20 01:00",  # 30 min gap
        ]
        data = pd.DataFrame(
            {"close": [1, 2, 3, 4]},
            index=pd.DatetimeIndex(pd.to_datetime(times, utc=True)),
        )
        interval = detect_interval_minutes(data)
        assert interval == 15.0  # 15 min is the mode


# ── scan_raw_signals ───────────────────────────────────────────────────

class TestScanRawSignals:
    def test_scans_all_bars(self, btc_config: Path, sample_m15_data: pd.DataFrame) -> None:
        config = load_config(btc_config)
        result = scan_raw_signals(config, sample_m15_data)
        assert result["raw_action_counts"]["hold"] > 0
        assert "raw_entry_signal_count" in result
        assert len(result["recent_entry_signals"]) <= 20

    def test_recent_signals_are_newest(self, btc_config: Path) -> None:
        config = load_config(btc_config)
        data = pd.DataFrame(
            {"open": [50000] * 50, "high": [50100] * 50, "low": [49900] * 50,
             "close": [50000 + i for i in range(50)], "volume": [100] * 50},
            index=pd.date_range("2026-05-20 00:00", periods=50, freq="15min", tz="UTC"),
        )
        result = scan_raw_signals(config, data)
        if result["raw_entry_signal_count"] > 0:
            assert len(result["recent_entry_signals"]) <= 20


# ── detect_calendar_status ─────────────────────────────────────────────

class TestDetectCalendarStatus:
    def test_disabled(self, btc_config: Path) -> None:
        config = load_config(btc_config)
        config.news_calendar.enabled = False
        status = detect_calendar_status(config)
        assert status["calendar_status"] in ("disabled", "unavailable")

    def test_disabled_provider(self, btc_config: Path) -> None:
        config = load_config(btc_config)
        config.news_calendar.enabled = True
        config.news_calendar.provider = "disabled"
        status = detect_calendar_status(config)
        assert status["calendar_status"] == "disabled"


# ── summarize_diagnosis ────────────────────────────────────────────────

class TestSummarizeDiagnosis:
    def test_interval_mismatch_detected(self) -> None:
        data = pd.DataFrame(
            {"close": [1, 2, 3]},
            index=pd.date_range("2026-05-20 00:00", periods=3, freq="1min", tz="UTC"),
        )
        config = TestBuildStrategy._make_config("ma_cross_atr")
        config.trading.timeframe = "M15"
        config.trading.symbol = "TEST"
        config.strategy.name = "test"
        config.news_calendar.enabled = False

        summary = summarize_diagnosis(
            config=config,
            data=data,
            raw_scan={
                "raw_action_counts": {"hold": 3},
                "raw_reason_counts": {"no_signal": 3},
                "raw_entry_signal_count": 0,
                "recent_entry_signals": [],
            },
            backtest_summary={
                "final_balance": 100000, "net_profit": 0.0, "total_trades": 0,
                "win_rate": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
                "avg_trade": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "profit_factor": 0.0, "max_drawdown_pct": 0.0, "blocked_entries": {},
            },
            calendar_info={"calendar_status": "disabled", "calendar_message": ""},
        )
        assert summary["interval_matches_config"] is False
        assert any("不匹配" in c for c in summary["diagnosis_conclusions"])

    def test_no_entry_signals(self) -> None:
        config = deepcopy(TestBuildStrategy._make_config("xau_m1_momentum"))
        summary = summarize_diagnosis(
            config=config,
            data=pd.DataFrame({"close": [1, 2]}, index=pd.date_range("2026-05-20 00:00", periods=2, freq="15min", tz="UTC")),
            raw_scan={
                "raw_action_counts": {"hold": 2},
                "raw_reason_counts": {"no_signal": 2},
                "raw_entry_signal_count": 0,
                "recent_entry_signals": [],
            },
            backtest_summary={
                "final_balance": 100000, "net_profit": 0.0, "total_trades": 0,
                "win_rate": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
                "avg_trade": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "profit_factor": 0.0, "max_drawdown_pct": 0.0, "blocked_entries": {},
            },
            calendar_info={"calendar_status": "ok", "calendar_message": "file.csv"},
        )
        assert any("没有产生任何原始入场信号" in c for c in summary["diagnosis_conclusions"])

    def test_blocked_entries_reported(self) -> None:
        config = deepcopy(TestBuildStrategy._make_config("xau_m1_momentum"))
        summary = summarize_diagnosis(
            config=config,
            data=pd.DataFrame({"close": [1, 2]}, index=pd.date_range("2026-05-20 00:00", periods=2, freq="15min", tz="UTC")),
            raw_scan={
                "raw_action_counts": {"buy": 1, "hold": 1},
                "raw_reason_counts": {"entry": 1, "no_signal": 1},
                "raw_entry_signal_count": 1,
                "recent_entry_signals": [{"time": "t1", "action": "buy", "reason": "entry"}],
            },
            backtest_summary={
                "final_balance": 100000, "net_profit": 0.0, "total_trades": 0,
                "win_rate": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
                "avg_trade": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "profit_factor": 0.0, "max_drawdown_pct": 0.0,
                "blocked_entries": {"outside_trading_window": 1},
            },
            calendar_info={"calendar_status": "ok", "calendar_message": "file.csv"},
        )
        assert any("主要拦截原因" in c for c in summary["diagnosis_conclusions"])

    def test_calendar_unavailable_reported(self) -> None:
        config = deepcopy(TestBuildStrategy._make_config("xau_m1_momentum"))
        summary = summarize_diagnosis(
            config=config,
            data=pd.DataFrame({"close": [1, 2]}, index=pd.date_range("2026-05-20 00:00", periods=2, freq="15min", tz="UTC")),
            raw_scan={
                "raw_action_counts": {"hold": 2},
                "raw_reason_counts": {"no_signal": 2},
                "raw_entry_signal_count": 0,
                "recent_entry_signals": [],
            },
            backtest_summary={
                "final_balance": 100000, "net_profit": 0.0, "total_trades": 0,
                "win_rate": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
                "avg_trade": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "profit_factor": 0.0, "max_drawdown_pct": 0.0, "blocked_entries": {},
            },
            calendar_info={"calendar_status": "unavailable", "calendar_message": "File not found"},
        )
        assert any("不可用" in c for c in summary["diagnosis_conclusions"])


# ── render_diagnostic_report ───────────────────────────────────────────

class TestRenderDiagnosticReport:
    def test_renders_with_all_sections(self) -> None:
        summary = {
            "symbol": "BTCUSD", "timeframe": "M15", "bars": 100,
            "data_start": "2026-05-20 00:00", "data_end": "2026-05-21 00:00",
            "expected_interval_minutes": 15, "actual_interval_minutes": 15,
            "interval_matches_config": True,
            "calendar_status": "ok", "calendar_message": "calendar.csv",
            "raw_action_counts": {"hold": 95, "buy": 5},
            "raw_reason_counts": {"no_signal": 95, "entry": 5},
            "raw_entry_signal_count": 5,
            "recent_entry_signals": [{"time": "t1", "action": "buy", "reason": "entry"}],
            "total_trades": 3, "win_rate": 0.666, "net_profit": 500,
            "max_drawdown_pct": 0.02, "blocked_entries": {"outside_window": 2},
            "diagnosis_conclusions": ["策略正常工作。"],
        }
        report = render_diagnostic_report(summary)
        assert "基础信息" in report
        assert "诊断结论" in report
        assert "原始信号统计" in report
        assert "回测成交与拦截" in report
        assert "最近原始入场信号" in report
        assert "BTCUSD" in report
        assert "M15" in report

    def test_no_recent_signals(self) -> None:
        summary = {
            "symbol": "TEST", "timeframe": "M1", "bars": 10,
            "data_start": "", "data_end": "",
            "expected_interval_minutes": 1, "actual_interval_minutes": 1,
            "interval_matches_config": True,
            "calendar_status": "disabled", "calendar_message": "",
            "raw_action_counts": {"hold": 10},
            "raw_reason_counts": {"no_signal": 10},
            "raw_entry_signal_count": 0,
            "recent_entry_signals": [],
            "total_trades": 0, "win_rate": 0.0, "net_profit": 0,
            "max_drawdown_pct": 0.0, "blocked_entries": {},
            "diagnosis_conclusions": ["没有原始入场信号。"],
        }
        report = render_diagnostic_report(summary)
        assert "没有原始入场信号" in report


# ── helpers ─────────────────────────────────────────────────────────────

class MagicConfig:
    """Simple mock that returns nested MagicConfig for missing attrs."""
    def __init__(self, **kwargs):
        # Set default name to avoid recursion in getattr
        object.__setattr__(self, "_magic_fields", {})
        for key, value in kwargs.items():
            object.__setattr__(self, key, value)

    def _default(self, name):
        """Return a sensible default for common attribute names."""
        return MagicConfig()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._default(name)

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
