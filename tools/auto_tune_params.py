#!/usr/bin/env python3
"""自动调参脚本：每日优化 breakout_atr_multiple，目标假突破率 < 15%。

用法:
    python tools/auto_tune_params.py --config configs/xauusd.m1.yaml --data history.csv

通过扫描最近 N 根 K 线中产生的入场信号，
统计「触发但未形成有效突破」的比例，动态调整 breakout_atr_multiple。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd
import yaml

from mt5_quant.config import load_config
from mt5_quant.diagnostics import load_csv_history
from mt5_quant.strategy.xau_m1_momentum import XauM1MomentumStrategy

LOGGER = logging.getLogger(__name__)


class BreakoutTuner:
    """XAU M1 策略的 breakout_atr_multiple 自动调优。"""

    def __init__(
        self,
        config_path: str | Path,
        data_path: str | Path,
        target_false_breakout_rate: float = 0.15,
        atr_multiple_range: list[float] = None,
        param_key: str = "strategy_params.breakout_atr_multiple",
    ) -> None:
        self.config_path = Path(config_path)
        self.data_path = Path(data_path)
        self.target_rate = target_false_breakout_rate
        self.param_key = param_key

        if atr_multiple_range is None:
            self.atr_multiple_range = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0]
        else:
            self.atr_multiple_range = atr_multiple_range

        self.config = load_config(str(self.config_path))
        self.data = load_csv_history(str(self.data_path))

    def run(self) -> dict:
        """执行调优，返回最佳参数和统计数据。"""
        results = []
        for multiple in self.atr_multiple_range:
            # 用新值创建临时配置
            self.config.strategy.breakout_atr_multiple = multiple
            strategy = XauM1MomentumStrategy(self.config.strategy)

            total_signals = 0
            false_breakouts = 0

            for idx in range(1, len(self.data)):
                signal = strategy.generate_signal(self.data.iloc[:idx], None)
                if signal.action in ("buy", "sell"):
                    total_signals += 1
                    # 简单判断假突破：入场后 5 根内反向突破
                    if idx + 5 < len(self.data):
                        subsequent = self.data.iloc[idx : idx + 5]
                        if signal.action == "buy":
                            # 买入后 low 低于入场 close → 假突破
                            if subsequent["low"].min() < float(self.data.iloc[idx - 1]["close"]):
                                false_breakouts += 1
                        elif signal.action == "sell":
                            if subsequent["high"].max() > float(self.data.iloc[idx - 1]["close"]):
                                false_breakouts += 1

            false_rate = false_breakouts / total_signals if total_signals > 0 else 1.0
            results.append(
                {
                    "breakout_atr_multiple": multiple,
                    "total_signals": total_signals,
                    "false_breakouts": false_breakouts,
                    "false_breakout_rate": round(false_rate, 4),
                }
            )
            LOGGER.info(
                "atr_multiple=%.1f total=%d false=%d rate=%.2f%%",
                multiple,
                total_signals,
                false_breakouts,
                false_rate * 100,
            )

        # 选假突破率小于目标 + 信号数最多的
        candidates = [r for r in results if r["false_breakout_rate"] <= self.target_rate]
        if not candidates:
            # 如果没有满足条件，选假突破率最低的
            best = min(results, key=lambda r: r["false_breakout_rate"])
            LOGGER.warning("没有参数满足目标假突破率，选择最低的: %.2f%%", best["false_breakout_rate"] * 100)
        else:
            best = max(candidates, key=lambda r: r["total_signals"])

        return {
            "best": best,
            "all": results,
            "updated_yaml": self._update_yaml(best["breakout_atr_multiple"]),
        }

    def _update_yaml(self, new_value: float) -> str:
        """更新 YAML 配置文件中的 breakout_atr_multiple。"""
        with self.config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}

        keys = self.param_key.split(".")
        target = raw
        for key in keys[:-1]:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
            target = target[key]
        target[keys[-1]] = new_value

        backup_path = self.config_path.with_suffix(".yaml.bak")
        self.config_path.rename(backup_path)
        with self.config_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(raw, handle, default_flow_style=False, allow_unicode=True)

        LOGGER.info("已更新 %s = %.2f（备份: %s）", self.param_key, new_value, backup_path)
        return str(self.config_path)

    def report(self, result: dict) -> str:
        """生成中文调优报告。"""
        best = result["best"]
        lines = [
            "# XAU M1 自动调参报告",
            "",
            f"- 目标假突破率：{self.target_rate * 100:.0f}%",
            f"- 数据样本：{len(self.data)} 根",
            f"- 当前最佳 breakout_atr_multiple：{best['breakout_atr_multiple']}",
            f"- 假突破率：{best['false_breakout_rate'] * 100:.2f}%",
            f"- 原始信号数：{best['total_signals']}",
            "",
            "## 全部参数测试结果",
            "",
            "| 参数值 | 信号数 | 假突破数 | 假突破率 |",
            "| --- | ---: | ---: | ---: |",
        ]
        for item in result["all"]:
            lines.append(
                f"| {item['breakout_atr_multiple']} | {item['total_signals']} | "
                f"{item['false_breakouts']} | {item['false_breakout_rate'] * 100:.2f}% |"
            )
        lines.append("")
        lines.append(f"配置文件已更新：{result.get('updated_yaml', '')}")
        return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="XAU M1 自动调参脚本")
    parser.add_argument("--config", required=True, help="XAU M1 YAML 配置文件路径")
    parser.add_argument("--data", required=True, help="CSV 历史数据路径")
    parser.add_argument(
        "--target-rate",
        type=float,
        default=0.15,
        help="目标假突破率 (默认 0.15)",
    )
    parser.add_argument(
        "--output",
        help="调优报告输出路径（可选）",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    tuner = BreakoutTuner(
        config_path=args.config,
        data_path=args.data,
        target_false_breakout_rate=args.target_rate,
    )
    result = tuner.run()
    report = tuner.report(result)

    print(report)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"\n报告已保存至: {args.output}")


if __name__ == "__main__":
    main()
