"""单元测试：config — 配置加载与校验。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mt5_quant.config import (
    AppConfig,
    ConfigError,
    NewsCalendarConfig,
    StrategyConfig,
    TIMEFRAME_ALIASES,
    load_config,
)


# ── helpers ──────────────────────────────────────────────────────────────

MINIMAL_YAML = """
mt5:
  login: 33
  password: "pass123"
  server: MetaQuotes-Demo
trading:
  symbol: XAUUSD
  timeframe: M1
strategy:
  name: xau_m1_momentum
backtest:
  initial_balance: 100000
"""


def write_yaml(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


# ── load_config ─────────────────────────────────────────────────────────

class TestLoadConfig:
    def test_load_minimal_yaml(self, tmp_path: Path) -> None:
        path = write_yaml(tmp_path, MINIMAL_YAML)
        cfg = load_config(path)
        assert isinstance(cfg, AppConfig)
        assert cfg.mt5.login == 33
        assert cfg.mt5.server == "MetaQuotes-Demo"
        assert cfg.trading.symbol == "XAUUSD"
        assert cfg.strategy.name == "xau_m1_momentum"

    def test_file_not_found(self) -> None:
        with pytest.raises(ConfigError, match="Config file not found"):
            load_config("/nonexistent/path.yaml")

    def test_root_not_mapping(self, tmp_path: Path) -> None:
        path = write_yaml(tmp_path, "[1, 2, 3]")
        with pytest.raises(ConfigError, match="Config root must be a mapping"):
            load_config(path)

    def test_missing_mt5_login(self, tmp_path: Path) -> None:
        path = write_yaml(tmp_path, MINIMAL_YAML.replace("login: 33", "# login: 33"))
        with pytest.raises(ConfigError, match="login"):
            load_config(path)

    def test_missing_mt5_password(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace('password: "pass123"', "# password: omitted")
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="password"):
            load_config(path)

    def test_unsupported_timeframe(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace("timeframe: M1", "timeframe: XYZ")
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="Unsupported timeframe"):
            load_config(path)

    def test_all_timeframe_aliases(self, tmp_path: Path) -> None:
        for alias in TIMEFRAME_ALIASES:
            yml = MINIMAL_YAML.replace("timeframe: M1", f"timeframe: {alias}")
            path = write_yaml(tmp_path, yml)
            cfg = load_config(path)
            assert cfg.trading.timeframe == alias

    def test_timeframe_casing_normalized(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace("timeframe: M1", "timeframe: m1")
        path = write_yaml(tmp_path, yml)
        cfg = load_config(path)
        assert cfg.trading.timeframe == "M1"

    def test_bar_time_shift_out_of_range(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace("timeframe: M1", "timeframe: M1\n  mt5_bar_time_shift_hours: 999")
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="mt5_bar_time_shift_hours"):
            load_config(path)

    def test_bar_time_shift_negative_allowed(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace(
            "trading:\n  symbol: XAUUSD\n  timeframe: M1",
            "trading:\n  symbol: XAUUSD\n  timeframe: M1\n  mt5_bar_time_shift_hours: -5",
        )
        path = write_yaml(tmp_path, yml)
        cfg = load_config(path)
        assert cfg.trading.mt5_bar_time_shift_hours == -5

    def test_risk_per_trade_must_be_between_0_and_1(self, tmp_path: Path) -> None:
        for bad_val in [0, -0.1, 1.0, 5]:
            yml = MINIMAL_YAML.replace(
                "strategy:\n  name: xau_m1_momentum",
                f"strategy:\n  name: xau_m1_momentum\n  risk_per_trade: {bad_val}",
            )
            path = write_yaml(tmp_path, yml)
            with pytest.raises(ConfigError, match="risk_per_trade"):
                load_config(path)

    def test_leverage_multiplier_must_be_positive(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace(
            "strategy:\n  name: xau_m1_momentum",
            "strategy:\n  name: xau_m1_momentum\n  leverage_multiplier: 0",
        )
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="leverage_multiplier"):
            load_config(path)


# ── per-strategy validation ─────────────────────────────────────────────

class TestStrategyValidation:
    def test_ema_cross_atr_requires_fast_less_than_slow(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace(
            "strategy:\n  name: xau_m1_momentum",
            "strategy:\n  name: ema_cross_atr\n  ema_fast: 55\n  ema_slow: 21",
        )
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="ema_fast must be smaller"):
            load_config(path)

    def test_ema_cross_atr_positive_stop_multiple(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace(
            "strategy:\n  name: xau_m1_momentum",
            "strategy:\n  name: ema_cross_atr\n  ema_fast: 10\n  ema_slow: 20\n  atr_stop_multiple: 0",
        )
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="atr_stop_multiple"):
            load_config(path)

    def test_ema_cross_atr_positive_reward_to_risk(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace(
            "strategy:\n  name: xau_m1_momentum",
            "strategy:\n  name: ema_cross_atr\n  ema_fast: 10\n  ema_slow: 20\n  reward_to_risk: 0",
        )
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="reward_to_risk"):
            load_config(path)

    def test_ma_cross_atr_short_vs_long_window(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace(
            "strategy:\n  name: xau_m1_momentum",
            "strategy:\n  name: ma_cross_atr\n  short_window: 50\n  long_window: 20",
        )
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="short_window"):
            load_config(path)

    def test_xau_m1_momentum_rsi_thresholds(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace(
            "strategy:\n  name: xau_m1_momentum",
            "strategy:\n  name: xau_m1_momentum\n  rsi_buy_threshold: 40\n  rsi_sell_threshold: 50",
        )
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="rsi_sell_threshold"):
            load_config(path)

    def test_xau_m1_momentum_take_profit_range(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace(
            "strategy:\n  name: xau_m1_momentum",
            "strategy:\n  name: xau_m1_momentum\n  take_profit_pct: 0",
        )
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="take_profit_pct"):
            load_config(path)

    def test_xau_m1_momentum_stop_loss_range(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace(
            "strategy:\n  name: xau_m1_momentum",
            "strategy:\n  name: xau_m1_momentum\n  stop_loss_pct: 1.5",
        )
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="stop_loss_pct"):
            load_config(path)

    def test_btc_m15_regime_adx_period_minimum(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace(
            "strategy:\n  name: xau_m1_momentum",
            "strategy:\n  name: btc_m15_regime\n  adx_period: 1",
        )
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="adx_period"):
            load_config(path)

    def test_btc_m15_regime_volume_window_minimum(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace(
            "strategy:\n  name: xau_m1_momentum",
            "strategy:\n  name: btc_m15_regime\n  volume_window: 0",
        )
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="volume_window"):
            load_config(path)

    def test_btc_m15_regime_breakout_buffer_non_negative(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace(
            "strategy:\n  name: xau_m1_momentum",
            "strategy:\n  name: btc_m15_regime\n  breakout_buffer_pct: -0.1",
        )
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="breakout_buffer_pct"):
            load_config(path)

    def test_unsupported_strategy_name_skips_validation(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML.replace(
            "strategy:\n  name: xau_m1_momentum",
            "strategy:\n  name: unknown_strategy",
        )
        path = write_yaml(tmp_path, yml)
        # Should load without per-strategy validation errors
        cfg = load_config(path)
        assert cfg.strategy.name == "unknown_strategy"


# ── safety validation ───────────────────────────────────────────────────

class TestSafetyValidation:
    def test_max_daily_loss_out_of_range(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML + "\nsafety:\n  max_daily_loss_pct: 1.5\n  timezone: Asia/Shanghai"
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="max_daily_loss_pct"):
            load_config(path)

    def test_max_consecutive_losses_below_one(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML + "\nsafety:\n  max_consecutive_losses: 0\n  timezone: Asia/Shanghai"
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="max_consecutive_losses"):
            load_config(path)

    def test_trailing_trigger_out_of_range(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML + "\nsafety:\n  trailing_trigger_pct: 1.2\n  timezone: Asia/Shanghai"
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="trailing_trigger_pct"):
            load_config(path)

    def test_trailing_distance_out_of_range(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML + "\nsafety:\n  trailing_distance_pct: -0.01\n  timezone: Asia/Shanghai"
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="trailing_distance_pct"):
            load_config(path)


# ── news calendar validation ────────────────────────────────────────────

class TestNewsCalendarValidation:
    def test_invalid_provider(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML + "\nnews_calendar:\n  provider: unknown_provider\n  enabled: true\n  api_key: ''\n  countries: []\n  importance: 3"
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="news_calendar.provider"):
            load_config(path)

    def test_disabled_provider_valid(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML + "\nnews_calendar:\n  enabled: false\n  provider: disabled"
        path = write_yaml(tmp_path, yml)
        cfg = load_config(path)
        assert cfg.news_calendar.enabled is False

    def test_importance_must_be_1_2_or_3(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML + "\nnews_calendar:\n  enabled: true\n  importance: 4\n  provider: mt5_file\n  api_key: ''\n  countries: []"
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="importance"):
            load_config(path)

    def test_blackout_minutes_non_negative(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML + "\nnews_calendar:\n  enabled: true\n  pre_blackout_minutes: -5\n  provider: mt5_file\n  api_key: ''\n  countries: []\n  importance: 3"
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="blackout minutes"):
            load_config(path)

    def test_lookahead_days_at_least_one(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML + "\nnews_calendar:\n  enabled: true\n  lookahead_days: 0\n  provider: mt5_file\n  api_key: ''\n  countries: []\n  importance: 3"
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="lookahead_days"):
            load_config(path)

    def test_cache_minutes_at_least_one(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML + "\nnews_calendar:\n  enabled: true\n  cache_minutes: 0\n  provider: mt5_file\n  api_key: ''\n  countries: []\n  importance: 3"
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="cache_minutes"):
            load_config(path)

    def test_request_timeout_at_least_one(self, tmp_path: Path) -> None:
        yml = MINIMAL_YAML + "\nnews_calendar:\n  enabled: true\n  request_timeout_seconds: 0\n  provider: mt5_file\n  api_key: ''\n  countries: []\n  importance: 3"
        path = write_yaml(tmp_path, yml)
        with pytest.raises(ConfigError, match="request_timeout_seconds"):
            load_config(path)

    def test_full_config_with_defaults(self, tmp_path: Path) -> None:
        """Verify all nested config sections load with defaults when absent."""
        minimal = """
mt5:
  login: 1
  password: p
  server: s
trading:
  symbol: XAUUSD
  timeframe: M1
strategy:
  name: xau_m1_momentum
"""
        path = write_yaml(tmp_path, minimal)
        cfg = load_config(path)
        # backtest defaults
        assert cfg.backtest.initial_balance == 100000
        assert cfg.backtest.spread_points == 10
        # safety defaults
        assert cfg.safety.timezone == "Asia/Shanghai"
        assert cfg.safety.max_daily_loss_pct == 0.02
        assert cfg.news_calendar.enabled is False
        assert cfg.news_calendar.provider == "mt5_file"
        # reporting defaults
        assert cfg.reporting.output_dir == "reports"
        assert cfg.reporting.save_summary_json is True
        # strategy defaults
        assert cfg.strategy.risk_per_trade == 0.01
        assert cfg.strategy.ema_fast == 21
