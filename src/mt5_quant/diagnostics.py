"""策略信号诊断模块。"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pandas as pd

from mt5_quant.backtest import BacktestEngine
from mt5_quant.config import AppConfig, load_config
from mt5_quant.data import Mt5Gateway
from mt5_quant.news_calendar import validate_calendar_data_source
from mt5_quant.strategy import BtcM15RegimeStrategy, EmaCrossAtrStrategy, MovingAverageAtrStrategy, XauM1MomentumStrategy


TIMEFRAME_TO_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}


def build_strategy(config: AppConfig):
    """根据配置构造策略实例。"""
    if config.strategy.name == "ema_cross_atr":
        return EmaCrossAtrStrategy(config.strategy)
    if config.strategy.name == "ma_cross_atr":
        return MovingAverageAtrStrategy(config.strategy)
    if config.strategy.name == "xau_m1_momentum":
        return XauM1MomentumStrategy(config.strategy)
    if config.strategy.name == "btc_m15_regime":
        return BtcM15RegimeStrategy(config.strategy)
    raise ValueError(f"Unsupported strategy: {config.strategy.name}")


def load_csv_history(path: str | Path) -> pd.DataFrame:
    """读取诊断所需的 CSV 历史数据。"""
    frame = pd.read_csv(path)
    required = {"time", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"CSV 缺少必要列: {sorted(missing)}")
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time")


def load_diagnostic_data(config: AppConfig, csv_path: str | None, bars: int | None) -> pd.DataFrame:
    """优先从 CSV 读取，否则从 MT5 拉取。"""
    if csv_path:
        return load_csv_history(csv_path)

    gateway = Mt5Gateway(config)
    gateway.connect()
    try:
        return gateway.get_rates(bars=bars or config.trading.history_bars)
    finally:
        gateway.shutdown()


def detect_calendar_status(config: AppConfig) -> dict[str, str]:
    """检查新闻文件状态，但不阻断诊断流程。"""
    if not config.news_calendar.enabled or config.news_calendar.provider == "disabled":
        return {"calendar_status": "disabled", "calendar_message": "已关闭自动财经日历。"}

    try:
        calendar_path = validate_calendar_data_source(
            config.news_calendar,
            config.safety.timezone,
            config.mt5.path,
        )
    except Exception as exc:
        return {"calendar_status": "unavailable", "calendar_message": str(exc)}

    if calendar_path is None:
        return {"calendar_status": "disabled", "calendar_message": "已关闭自动财经日历。"}
    return {"calendar_status": "ok", "calendar_message": str(calendar_path)}


def detect_interval_minutes(data: pd.DataFrame) -> float | None:
    """推断样本主时间间隔。"""
    if len(data.index) < 2:
        return None
    interval = data.index.to_series().diff().dropna()
    if interval.empty:
        return None
    return float(interval.mode().iloc[0].total_seconds() / 60)


def scan_raw_signals(config: AppConfig, data: pd.DataFrame) -> dict[str, Any]:
    """扫描原始策略信号，不考虑是否已持仓。"""
    strategy = build_strategy(config)
    action_counter: Counter[str] = Counter()
    reason_counter: Counter[str] = Counter()
    entry_signals: list[dict[str, str]] = []

    for index in range(1, len(data) + 1):
        signal = strategy.generate_signal(data.iloc[:index], None)
        action_counter[signal.action] += 1
        reason_counter[signal.reason] += 1
        if signal.action in {"buy", "sell"}:
            entry_signals.append(
                {
                    "time": str(data.index[index - 1]),
                    "action": signal.action,
                    "reason": signal.reason,
                }
            )

    return {
        "raw_action_counts": dict(action_counter),
        "raw_reason_counts": dict(reason_counter),
        "raw_entry_signal_count": len(entry_signals),
        "recent_entry_signals": entry_signals[-20:],
    }


def summarize_diagnosis(
    config: AppConfig,
    data: pd.DataFrame,
    raw_scan: dict[str, Any],
    backtest_summary: dict[str, Any],
    calendar_info: dict[str, str],
) -> dict[str, Any]:
    """生成用户可读的诊断结论。"""
    actual_interval = detect_interval_minutes(data)
    expected_interval = TIMEFRAME_TO_MINUTES.get(config.trading.timeframe)
    interval_matches = actual_interval == expected_interval if actual_interval is not None else False

    total_trades = int(backtest_summary["total_trades"])
    blocked_entries = dict(backtest_summary.get("blocked_entries", {}))
    raw_entry_signal_count = int(raw_scan["raw_entry_signal_count"])

    conclusions: list[str] = []
    if actual_interval is None:
        conclusions.append("样本数据过短，无法判断时间周期。")
    elif expected_interval is not None and not interval_matches:
        conclusions.append(
            f"样本周期与配置不匹配：配置是 {config.trading.timeframe}，"
            f"但数据主间隔约为 {actual_interval:.0f} 分钟。"
        )

    if raw_entry_signal_count == 0:
        conclusions.append("策略在这段样本上没有产生任何原始入场信号，优先检查样本质量或参数是否过严。")
    elif total_trades == 0 and blocked_entries:
        conclusions.append(f"策略有原始信号，但成交被风控或时间窗拦截，主要拦截原因：{blocked_entries}。")
    elif total_trades == 0:
        conclusions.append("策略有原始信号但最终没有成交，常见原因是启动时已错过收盘信号，或当时已有持仓。")
    else:
        conclusions.append(f"策略在该样本上可以正常触发，已成交 {total_trades} 笔。")

    if calendar_info["calendar_status"] == "unavailable":
        conclusions.append("自动财经日历当前不可用，真实运行前应先修复新闻文件导出。")

    return {
        "symbol": config.trading.symbol,
        "timeframe": config.trading.timeframe,
        "bars": len(data),
        "data_start": str(data.index.min()) if not data.empty else "",
        "data_end": str(data.index.max()) if not data.empty else "",
        "expected_interval_minutes": expected_interval,
        "actual_interval_minutes": actual_interval,
        "interval_matches_config": interval_matches,
        "calendar_status": calendar_info["calendar_status"],
        "calendar_message": calendar_info["calendar_message"],
        **raw_scan,
        **backtest_summary,
        "diagnosis_conclusions": conclusions,
    }


def render_diagnostic_report(summary: dict[str, Any]) -> str:
    """输出中文诊断报告。"""
    lines = [
        "# 策略信号诊断报告",
        "",
        "## 一、基础信息",
        "",
        f"- 交易品种：`{summary['symbol']}`",
        f"- 配置周期：`{summary['timeframe']}`",
        f"- 样本数量：`{summary['bars']}`",
        f"- 样本开始：`{summary['data_start']}`",
        f"- 样本结束：`{summary['data_end']}`",
        f"- 预期周期分钟数：`{summary['expected_interval_minutes']}`",
        f"- 实际样本主间隔分钟数：`{summary['actual_interval_minutes']}`",
        f"- 周期是否匹配配置：`{summary['interval_matches_config']}`",
        f"- 财经日历状态：`{summary['calendar_status']}`",
        f"- 财经日历说明：`{summary['calendar_message']}`",
        "",
        "## 二、诊断结论",
        "",
    ]
    for item in summary["diagnosis_conclusions"]:
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## 三、原始信号统计",
            "",
            f"- 原始入场信号总数：`{summary['raw_entry_signal_count']}`",
            f"- 原始动作分布：`{json.dumps(summary['raw_action_counts'], ensure_ascii=False)}`",
            f"- 原始原因分布：`{json.dumps(summary['raw_reason_counts'], ensure_ascii=False)}`",
            "",
            "## 四、回测成交与拦截",
            "",
            f"- 成交笔数：`{summary['total_trades']}`",
            f"- 胜率：`{summary['win_rate']}`",
            f"- 净利润：`{summary['net_profit']}`",
            f"- 最大回撤：`{summary['max_drawdown_pct']}`",
            f"- 拦截统计：`{json.dumps(summary['blocked_entries'], ensure_ascii=False)}`",
            "",
            "## 五、最近原始入场信号",
            "",
        ]
    )

    if summary["recent_entry_signals"]:
        for item in summary["recent_entry_signals"]:
            lines.append(f"- `{item['time']}` | `{item['action']}` | `{item['reason']}`")
    else:
        lines.append("- 最近样本内没有原始入场信号。")

    return "\n".join(lines)


def run_signal_diagnosis(
    config_path: str | Path,
    csv_path: str | None,
    bars: int | None,
    output_dir: str | Path,
) -> dict[str, Any]:
    """执行策略信号诊断。"""
    config = load_config(config_path)
    calendar_info = detect_calendar_status(config)
    data = load_diagnostic_data(config, csv_path, bars)
    raw_scan = scan_raw_signals(config, data)

    backtest_config = deepcopy(config)
    if calendar_info["calendar_status"] != "ok":
        backtest_config.news_calendar.enabled = False
    result = BacktestEngine(backtest_config, build_strategy(backtest_config)).run(data)
    backtest_summary = {key: value for key, value in result.items() if key not in {"trades", "equity_curve"}}
    summary = summarize_diagnosis(config, data, raw_scan, backtest_summary, calendar_info)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "diagnosis_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_path / "diagnosis_report.md").write_text(
        render_diagnostic_report(summary),
        encoding="utf-8",
    )
    return summary
