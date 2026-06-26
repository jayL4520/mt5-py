#!/usr/bin/env python3
"""多周期信号诊断脚本：M1/M5/M15 对比表格 + 建议语句。

用法:
    python tools/diagnose_xau_signals.py --data history.csv --output report.md

对同一份样本数据，分别在 M1 / M5 / M15 三种周期运行诊断，
输出信号数量、胜率、盈亏比、最大连亏等指标对比。
"""

from __future__ import annotations

import argparse
import json
import logging
from copy import deepcopy
from pathlib import Path

import pandas as pd

from mt5_quant.backtest import BacktestEngine
from mt5_quant.config import (
    AppConfig,
    BacktestConfig,
    Mt5Config,
    NewsCalendarConfig,
    ReportingConfig,
    SafetyConfig,
    StrategyConfig,
    TradingConfig,
    load_config,
)
from mt5_quant.diagnostics import load_csv_history, scan_raw_signals
from mt5_quant.strategy import XauM15WaveStrategy, XauM1MomentumStrategy, XauM5WaveStrategy

LOGGER = logging.getLogger(__name__)

# 各周期的策略名称、参数模板
TIMEFRAME_STRATEGIES = {
    "M1": {
        "strategy_name": "xau_m1_momentum",
        "class": XauM1MomentumStrategy,
        "params": {
            "ema_fast": 9,
            "ema_slow": 21,
            "rsi_period": 14,
            "rsi_buy_threshold": 55.0,
            "rsi_sell_threshold": 45.0,
            "breakout_lookback": 20,
            "take_profit_pct": 0.003,
            "stop_loss_pct": 0.004,
            "volume_window": 20,
            "volume_multiplier": 1.0,
            "breakout_buffer_pct": 0.0,
            "atr_period": 14,
            "atr_stop_multiple": 2.0,
            "reward_to_risk": 2.0,
            "risk_per_trade": 0.01,
            "leverage_multiplier": 1.0,
        },
    },
    "M5": {
        "strategy_name": "xau_m5_wave",
        "class": XauM5WaveStrategy,
        "params": {
            "ema_fast": 12,
            "ema_mid": 30,
            "ema_slow": 70,
            "rsi_period": 14,
            "atr_period": 20,
            "atr_stop_multiple": 2.0,
            "reward_to_risk": 2.5,
            "atr_min_threshold": 10.0,
            "risk_per_trade": 0.01,
            "leverage_multiplier": 1.0,
        },
    },
    "M15": {
        "strategy_name": "xau_m15_wave",
        "class": XauM15WaveStrategy,
        "params": {
            "ema_fast": 12,
            "ema_mid": 30,
            "ema_slow": 70,
            "rsi_period": 14,
            "atr_period": 20,
            "atr_stop_multiple": 2.0,
            "reward_to_risk": 2.5,
            "atr_min_threshold": 15.0,
            "risk_per_trade": 0.01,
            "leverage_multiplier": 1.0,
        },
    },
}


def build_base_config() -> AppConfig:
    """构造一个基础的 AppConfig 用于多周期诊断。"""
    return AppConfig(
        mt5=Mt5Config(login=1, password="p", server="s"),
        trading=TradingConfig(
            symbol="XAUUSD",
            timeframe="M1",
            history_bars=5000,
            mt5_bar_time_shift_hours=0,
            slippage_points=20,
            magic_number=260516,
            comment="diagnose",
            poll_interval_seconds=5,
            max_open_positions=1,
        ),
        strategy=StrategyConfig(
            name="xau_m1_momentum",
            risk_per_trade=0.01,
            short_window=20,
            long_window=50,
            atr_period=14,
            atr_stop_multiple=2.0,
            reward_to_risk=2.0,
            leverage_multiplier=1.0,
            ema_fast=21,
            ema_slow=55,
            rsi_period=14,
            rsi_buy_threshold=55.0,
            rsi_sell_threshold=45.0,
            breakout_lookback=20,
            take_profit_pct=0.003,
            stop_loss_pct=0.004,
            adx_period=14,
            adx_threshold=22.0,
            volume_window=20,
            volume_multiplier=1.0,
            breakout_buffer_pct=0.0,
        ),
        backtest=BacktestConfig(
            initial_balance=100000,
            commission_per_lot=0.0,
            spread_points=10,
            contract_size=1.0,
        ),
        safety=SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=6,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=False,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ),
        news_calendar=NewsCalendarConfig(
            enabled=False,
            provider="disabled",
            api_key="",
            countries=[],
            importance=3,
            pre_blackout_minutes=10,
            post_blackout_minutes=10,
            lookahead_days=7,
            cache_minutes=30,
            request_timeout_seconds=20,
            common_filename="",
            file_path="",
        ),
        reporting=ReportingConfig(
            output_dir="reports",
            save_summary_json=True,
            save_trades_csv=True,
            save_equity_csv=True,
        ),
    )


def run_diagnose(data: pd.DataFrame) -> list[dict]:
    """对 M1/M5/M15 三个周期分别诊断，返回对比列表。"""
    results = []

    for tf, meta in TIMEFRAME_STRATEGIES.items():
        config = build_base_config()
        config.trading.timeframe = tf

        # 更新策略参数
        for key, value in meta["params"].items():
            setattr(config.strategy, key, value)
        config.strategy.name = meta["strategy_name"]

        # 构建策略实例
        strategy_class = meta["class"]
        strategy = strategy_class(config.strategy)

        # 扫描原始信号
        raw_scan = scan_raw_signals(config, data)

        # 运行回测
        engine = BacktestEngine(config, strategy)
        result = engine.run(data)
        summary = {k: v for k, v in result.items() if k not in {"trades", "equity_curve"}}

        # 计算最大连亏
        max_consecutive_losses = 0
        current_loss_streak = 0
        for trade in result.get("trades", []):
            if float(trade.get("pnl", 0)) < 0:
                current_loss_streak += 1
                max_consecutive_losses = max(max_consecutive_losses, current_loss_streak)
            else:
                current_loss_streak = 0

        results.append(
            {
                "timeframe": tf,
                "total_signals": raw_scan["raw_entry_signal_count"],
                "total_trades": int(summary.get("total_trades", 0)),
                "win_rate": round(float(summary.get("win_rate", 0)), 4),
                "net_profit": round(float(summary.get("net_profit", 0)), 2),
                "profit_factor": round(float(summary.get("profit_factor", 0)), 4),
                "max_drawdown_pct": round(float(summary.get("max_drawdown_pct", 0)), 4),
                "max_consecutive_losses": max_consecutive_losses,
                "avg_trade": round(float(summary.get("avg_trade", 0)), 2),
            }
        )
        LOGGER.info(
            "诊断完成 %s: 信号=%d 成交=%d 胜率=%.2f%% 净利润=%.2f",
            tf,
            results[-1]["total_signals"],
            results[-1]["total_trades"],
            results[-1]["win_rate"] * 100,
            results[-1]["net_profit"],
        )

    return results


def generate_suggestion(results: list[dict]) -> str:
    """根据诊断结果生成一句话建议。"""
    if not results:
        return "无诊断数据。"

    # 找最佳周期
    best = max(results, key=lambda r: r["net_profit"])

    suggestions = []
    suggestions.append(f"建议使用周期：{best['timeframe']}（净利润 {best['net_profit']}，胜率 {best['win_rate'] * 100:.1f}%）")

    for item in results:
        if item["max_consecutive_losses"] >= 5:
            suggestions.append(
                f"⚠️ {item['timeframe']} 最大连亏 {item['max_consecutive_losses']} 次，建议先检查参数或切换周期。"
            )
        if item["profit_factor"] < 1.0:
            suggestions.append(
                f"⚠️ {item['timeframe']} 盈亏比 {item['profit_factor']:.2f} < 1.0，不宜单独使用。"
            )

    return " | ".join(suggestions)


def render_report(results: list[dict], data_len: int, suggestion: str) -> str:
    """生成中文多周期诊断报告。"""
    lines = [
        "# XAUUSD 多周期信号诊断报告",
        "",
        f"- 数据样本：{data_len} 根 K 线",
        f"- 诊断日期：{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 一、多周期对比表格",
        "",
        "| 周期 | 原始信号 | 成交笔数 | 胜率 | 净利润 | 盈亏比 | 最大回撤 | 最大连亏 | 平均盈亏 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for item in results:
        lines.append(
            f"| {item['timeframe']} | {item['total_signals']} | {item['total_trades']} | "
            f"{item['win_rate'] * 100:.2f}% | {item['net_profit']:.2f} | "
            f"{item['profit_factor']:.2f} | {item['max_drawdown_pct'] * 100:.2f}% | "
            f"{item['max_consecutive_losses']} | {item['avg_trade']:.2f} |"
        )

    lines.extend(
        [
            "",
            "## 二、诊断建议",
            "",
            f"{suggestion}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="XAUUSD 多周期信号诊断脚本")
    parser.add_argument("--data", required=True, help="CSV 历史数据路径")
    parser.add_argument("--output", help="诊断报告输出路径（可选）")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    data = load_csv_history(args.data)
    LOGGER.info("已加载 %d 根 K 线数据", len(data))

    results = run_diagnose(data)
    suggestion = generate_suggestion(results)
    report = render_report(results, len(data), suggestion)

    print(report)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"\n报告已保存至: {args.output}")


if __name__ == "__main__":
    main()
