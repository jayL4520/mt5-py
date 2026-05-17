"""配置加载模块。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


TIMEFRAME_ALIASES = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


class ConfigError(ValueError):
    pass


@dataclass(slots=True)
class Mt5Config:
    login: int
    password: str
    server: str
    path: str = ""
    timeout: int = 60000
    portable: bool = False


@dataclass(slots=True)
class TradingConfig:
    symbol: str
    timeframe: str
    history_bars: int
    slippage_points: int
    magic_number: int
    comment: str
    poll_interval_seconds: int
    max_open_positions: int


@dataclass(slots=True)
class StrategyConfig:
    name: str
    short_window: int
    long_window: int
    atr_period: int
    atr_stop_multiple: float
    reward_to_risk: float
    risk_per_trade: float
    ema_fast: int
    ema_slow: int
    rsi_period: int
    rsi_buy_threshold: float
    rsi_sell_threshold: float
    breakout_lookback: int
    take_profit_pct: float
    stop_loss_pct: float
    adx_period: int
    adx_threshold: float
    volume_window: int
    volume_multiplier: float
    breakout_buffer_pct: float


@dataclass(slots=True)
class BacktestConfig:
    initial_balance: float
    commission_per_lot: float
    spread_points: float
    contract_size: float


@dataclass(slots=True)
class SafetyConfig:
    timezone: str
    trading_windows: list[str]
    max_daily_loss_pct: float
    max_consecutive_losses: int
    one_direction_per_day: bool
    news_blackout_windows: list[str]
    trailing_stop_enabled: bool
    trailing_trigger_pct: float
    trailing_distance_pct: float


@dataclass(slots=True)
class NewsCalendarConfig:
    enabled: bool
    provider: str
    api_key: str
    countries: list[str]
    importance: int
    pre_blackout_minutes: int
    post_blackout_minutes: int
    lookahead_days: int
    cache_minutes: int
    request_timeout_seconds: int
    common_filename: str
    file_path: str


@dataclass(slots=True)
class ReportingConfig:
    output_dir: str
    save_summary_json: bool
    save_trades_csv: bool
    save_equity_csv: bool


@dataclass(slots=True)
class AppConfig:
    mt5: Mt5Config
    trading: TradingConfig
    strategy: StrategyConfig
    backtest: BacktestConfig
    safety: SafetyConfig
    news_calendar: NewsCalendarConfig
    reporting: ReportingConfig


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError("Config root must be a mapping.")
    return data


def _required(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"Missing required config key: {key}")
    return mapping[key]


def load_config(path: str | Path) -> AppConfig:
    raw = _read_yaml(Path(path))
    mt5 = _required(raw, "mt5")
    trading = _required(raw, "trading")
    strategy = _required(raw, "strategy")
    backtest = raw.get("backtest", {})
    safety = raw.get("safety", {})
    news_calendar = raw.get("news_calendar", {})
    reporting = raw.get("reporting", {})

    cfg = AppConfig(
        mt5=Mt5Config(
            login=int(_required(mt5, "login")),
            password=str(_required(mt5, "password")),
            server=str(_required(mt5, "server")),
            path=str(mt5.get("path", "")),
            timeout=int(mt5.get("timeout", 60000)),
            portable=bool(mt5.get("portable", False)),
        ),
        trading=TradingConfig(
            symbol=str(_required(trading, "symbol")),
            timeframe=str(_required(trading, "timeframe")).upper(),
            history_bars=int(trading.get("history_bars", 800)),
            slippage_points=int(trading.get("slippage_points", 20)),
            magic_number=int(trading.get("magic_number", 260516)),
            comment=str(trading.get("comment", "mt5-quant")),
            poll_interval_seconds=int(trading.get("poll_interval_seconds", 5)),
            max_open_positions=int(trading.get("max_open_positions", 1)),
        ),
        strategy=StrategyConfig(
            name=str(strategy.get("name", "ma_cross_atr")),
            short_window=int(strategy.get("short_window", 20)),
            long_window=int(strategy.get("long_window", 50)),
            atr_period=int(strategy.get("atr_period", 14)),
            atr_stop_multiple=float(strategy.get("atr_stop_multiple", 2.0)),
            reward_to_risk=float(strategy.get("reward_to_risk", 2.0)),
            risk_per_trade=float(strategy.get("risk_per_trade", 0.01)),
            ema_fast=int(strategy.get("ema_fast", 21)),
            ema_slow=int(strategy.get("ema_slow", 55)),
            rsi_period=int(strategy.get("rsi_period", 14)),
            rsi_buy_threshold=float(strategy.get("rsi_buy_threshold", 55.0)),
            rsi_sell_threshold=float(strategy.get("rsi_sell_threshold", 45.0)),
            breakout_lookback=int(strategy.get("breakout_lookback", 20)),
            take_profit_pct=float(strategy.get("take_profit_pct", 0.003)),
            stop_loss_pct=float(strategy.get("stop_loss_pct", 0.004)),
            adx_period=int(strategy.get("adx_period", 14)),
            adx_threshold=float(strategy.get("adx_threshold", 22.0)),
            volume_window=int(strategy.get("volume_window", 20)),
            volume_multiplier=float(strategy.get("volume_multiplier", 1.0)),
            breakout_buffer_pct=float(strategy.get("breakout_buffer_pct", 0.0)),
        ),
        backtest=BacktestConfig(
            initial_balance=float(backtest.get("initial_balance", 100000)),
            commission_per_lot=float(backtest.get("commission_per_lot", 0.0)),
            spread_points=float(backtest.get("spread_points", 10)),
            contract_size=float(backtest.get("contract_size", 1.0)),
        ),
        safety=SafetyConfig(
            timezone=str(safety.get("timezone", "Asia/Shanghai")),
            trading_windows=[str(value) for value in safety.get("trading_windows", ["14:00-02:00"])],
            max_daily_loss_pct=float(safety.get("max_daily_loss_pct", 0.02)),
            max_consecutive_losses=int(safety.get("max_consecutive_losses", 3)),
            one_direction_per_day=bool(safety.get("one_direction_per_day", True)),
            news_blackout_windows=[str(value) for value in safety.get("news_blackout_windows", [])],
            trailing_stop_enabled=bool(safety.get("trailing_stop_enabled", True)),
            trailing_trigger_pct=float(safety.get("trailing_trigger_pct", 0.0015)),
            trailing_distance_pct=float(safety.get("trailing_distance_pct", 0.0012)),
        ),
        news_calendar=NewsCalendarConfig(
            enabled=bool(news_calendar.get("enabled", False)),
            provider=str(news_calendar.get("provider", "mt5_file")).lower(),
            api_key=str(news_calendar.get("api_key", "guest:guest")),
            countries=[str(value) for value in news_calendar.get("countries", ["united states"])],
            importance=int(news_calendar.get("importance", 3)),
            pre_blackout_minutes=int(news_calendar.get("pre_blackout_minutes", 10)),
            post_blackout_minutes=int(news_calendar.get("post_blackout_minutes", 10)),
            lookahead_days=int(news_calendar.get("lookahead_days", 7)),
            cache_minutes=int(news_calendar.get("cache_minutes", 30)),
            request_timeout_seconds=int(news_calendar.get("request_timeout_seconds", 20)),
            common_filename=str(news_calendar.get("common_filename", "mt5_calendar_events.csv")),
            file_path=str(news_calendar.get("file_path", "")),
        ),
        reporting=ReportingConfig(
            output_dir=str(reporting.get("output_dir", "reports")),
            save_summary_json=bool(reporting.get("save_summary_json", True)),
            save_trades_csv=bool(reporting.get("save_trades_csv", True)),
            save_equity_csv=bool(reporting.get("save_equity_csv", True)),
        ),
    )

    if cfg.trading.timeframe not in TIMEFRAME_ALIASES:
        allowed = ", ".join(TIMEFRAME_ALIASES)
        raise ConfigError(f"Unsupported timeframe {cfg.trading.timeframe}. Allowed: {allowed}")

    if not 0 < cfg.strategy.risk_per_trade < 1:
        raise ConfigError("strategy.risk_per_trade must be between 0 and 1.")

    if cfg.strategy.name == "ma_cross_atr" and cfg.strategy.short_window >= cfg.strategy.long_window:
        raise ConfigError("strategy.short_window must be smaller than strategy.long_window.")

    if cfg.strategy.name == "xau_m1_momentum":
        if cfg.strategy.ema_fast >= cfg.strategy.ema_slow:
            raise ConfigError("strategy.ema_fast must be smaller than strategy.ema_slow.")
        if not 0 < cfg.strategy.take_profit_pct < 1:
            raise ConfigError("strategy.take_profit_pct must be between 0 and 1.")
        if not 0 < cfg.strategy.stop_loss_pct < 1:
            raise ConfigError("strategy.stop_loss_pct must be between 0 and 1.")
        if cfg.strategy.rsi_sell_threshold >= cfg.strategy.rsi_buy_threshold:
            raise ConfigError("strategy.rsi_sell_threshold must be smaller than strategy.rsi_buy_threshold.")

    if cfg.strategy.name == "btc_m15_regime":
        if cfg.strategy.ema_fast >= cfg.strategy.ema_slow:
            raise ConfigError("strategy.ema_fast must be smaller than strategy.ema_slow.")
        if cfg.strategy.adx_period < 2:
            raise ConfigError("strategy.adx_period must be at least 2.")
        if cfg.strategy.adx_threshold <= 0:
            raise ConfigError("strategy.adx_threshold must be greater than 0.")
        if cfg.strategy.volume_window < 1:
            raise ConfigError("strategy.volume_window must be at least 1.")
        if cfg.strategy.volume_multiplier < 0:
            raise ConfigError("strategy.volume_multiplier must be greater than or equal to 0.")
        if cfg.strategy.breakout_buffer_pct < 0:
            raise ConfigError("strategy.breakout_buffer_pct must be greater than or equal to 0.")
        if cfg.strategy.atr_stop_multiple <= 0:
            raise ConfigError("strategy.atr_stop_multiple must be greater than 0.")
        if cfg.strategy.reward_to_risk <= 0:
            raise ConfigError("strategy.reward_to_risk must be greater than 0.")

    if not 0 <= cfg.safety.max_daily_loss_pct < 1:
        raise ConfigError("safety.max_daily_loss_pct must be between 0 and 1.")

    if cfg.safety.max_consecutive_losses < 1:
        raise ConfigError("safety.max_consecutive_losses must be at least 1.")

    if not 0 <= cfg.safety.trailing_trigger_pct < 1:
        raise ConfigError("safety.trailing_trigger_pct must be between 0 and 1.")

    if not 0 <= cfg.safety.trailing_distance_pct < 1:
        raise ConfigError("safety.trailing_distance_pct must be between 0 and 1.")

    if cfg.news_calendar.provider not in {"disabled", "tradingeconomics", "mt5_file"}:
        raise ConfigError("news_calendar.provider must be one of: disabled, tradingeconomics, mt5_file.")

    if cfg.news_calendar.enabled:
        if cfg.news_calendar.importance not in {1, 2, 3}:
            raise ConfigError("news_calendar.importance must be 1, 2, or 3.")
        if cfg.news_calendar.pre_blackout_minutes < 0 or cfg.news_calendar.post_blackout_minutes < 0:
            raise ConfigError("news blackout minutes must be greater than or equal to 0.")
        if cfg.news_calendar.lookahead_days < 1:
            raise ConfigError("news_calendar.lookahead_days must be at least 1.")
        if cfg.news_calendar.cache_minutes < 1:
            raise ConfigError("news_calendar.cache_minutes must be at least 1.")
        if cfg.news_calendar.request_timeout_seconds < 1:
            raise ConfigError("news_calendar.request_timeout_seconds must be at least 1.")

    return cfg
