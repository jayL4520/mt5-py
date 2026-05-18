"""BTC 策略参数优化与中文回测报告输出模块。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import fields
from itertools import product
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd
import yaml

from mt5_quant.backtest import BacktestEngine
from mt5_quant.config import AppConfig, StrategyConfig, load_config
from mt5_quant.launcher_profiles import resolve_runtime_root
from mt5_quant.news_calendar import validate_calendar_data_source
from mt5_quant.strategy import BtcM15RegimeStrategy


DEFAULT_TEMPLATE_PATH = Path("templates") / "btc_optimization_template.yaml"
DEFAULT_REPORT_TEMPLATE_PATH = Path("templates") / "btc_backtest_report_template.md"


def resolve_worker_count(max_workers: int | None, total_tasks: int) -> int:
    """解析参数优化线程数。"""
    if total_tasks <= 1:
        return 1
    if max_workers is not None:
        return max(1, min(max_workers, total_tasks))
    cpu_count = os.cpu_count() or 1
    return max(1, min(cpu_count, total_tasks, 8))


def load_csv_history(path: str | Path) -> pd.DataFrame:
    """读取 BTC 优化所需的 CSV 历史数据。"""
    frame = pd.read_csv(path)
    required = {"time", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"CSV 缺少必要列: {sorted(missing)}")
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time")


def resolve_template_path(path: str | None, default_relative_path: Path) -> Path:
    """优先读取当前目录模板，读不到再回退到项目或打包内模板。"""
    if path:
        resolved = Path(path)
        if resolved.exists():
            return resolved
        raise FileNotFoundError(f"模板文件不存在: {resolved}")

    cwd_path = Path.cwd() / default_relative_path
    if cwd_path.exists():
        return cwd_path

    runtime_path = resolve_runtime_root() / default_relative_path
    if runtime_path.exists():
        return runtime_path

    raise FileNotFoundError(f"未找到默认模板文件: {default_relative_path}")


def load_optimization_template(path: str | None = None) -> dict[str, Any]:
    """读取 BTC 参数优化模板。"""
    template_path = resolve_template_path(path, DEFAULT_TEMPLATE_PATH)
    with template_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("参数优化模板根节点必须是字典。")
    return data


def build_parameter_grid(grid_config: dict[str, Any]) -> list[dict[str, Any]]:
    """把 YAML 中的参数网格展开成组合列表。"""
    if not grid_config:
        raise ValueError("参数优化模板未提供 strategy_grid。")

    strategy_fields = {item.name for item in fields(StrategyConfig)}
    invalid_keys = sorted(set(grid_config) - strategy_fields)
    if invalid_keys:
        raise ValueError(f"参数优化模板里存在未知策略字段: {invalid_keys}")

    keys: list[str] = []
    values_list: list[list[Any]] = []
    for key, raw_values in grid_config.items():
        if not isinstance(raw_values, list) or not raw_values:
            raise ValueError(f"参数字段 {key} 必须提供非空列表。")
        keys.append(key)
        values_list.append(raw_values)

    return [dict(zip(keys, combination, strict=False)) for combination in product(*values_list)]


def validate_btc_parameter_set(strategy: StrategyConfig) -> str | None:
    """校验单组 BTC 参数是否自洽。"""
    if strategy.ema_fast >= strategy.ema_slow:
        return "ema_fast 必须小于 ema_slow"
    if strategy.adx_period < 2:
        return "adx_period 必须大于等于 2"
    if strategy.adx_threshold <= 0:
        return "adx_threshold 必须大于 0"
    if strategy.volume_window < 1:
        return "volume_window 必须大于等于 1"
    if strategy.volume_multiplier < 0:
        return "volume_multiplier 必须大于等于 0"
    if strategy.breakout_buffer_pct < 0:
        return "breakout_buffer_pct 不能小于 0"
    if strategy.atr_stop_multiple <= 0:
        return "atr_stop_multiple 必须大于 0"
    if strategy.reward_to_risk <= 0:
        return "reward_to_risk 必须大于 0"
    return None


def apply_strategy_overrides(config: AppConfig, overrides: dict[str, Any]) -> AppConfig:
    """基于基础配置应用一组策略参数。"""
    updated = deepcopy(config)
    for key, value in overrides.items():
        setattr(updated.strategy, key, value)
    return updated


def is_candidate_qualified(
    result: dict[str, Any],
    qualification: dict[str, Any],
) -> tuple[bool, str]:
    """根据模板中的门槛过滤无效组合。"""
    min_trades = int(qualification.get("min_trades", 1))
    max_drawdown_pct = float(qualification.get("max_drawdown_pct", 1.0))
    min_profit_factor = float(qualification.get("min_profit_factor", 0.0))

    if int(result["total_trades"]) < min_trades:
        return False, "成交笔数不足"
    if float(result["max_drawdown_pct"]) > max_drawdown_pct:
        return False, "最大回撤超限"
    if float(result["profit_factor"]) < min_profit_factor:
        return False, "盈亏比不足"
    return True, "通过"


def metric_sort_value(metric: str, value: float) -> float:
    """统一排序方向，大多数指标越大越好，回撤越小越好。"""
    if metric == "max_drawdown_pct":
        return float(value)
    return -float(value)


def rank_candidates(
    rows: list[dict[str, Any]],
    ranking: dict[str, Any],
) -> list[dict[str, Any]]:
    """对参数组合结果进行排序。"""
    primary_metric = str(ranking.get("primary_metric", "net_profit"))
    secondary_metric = str(ranking.get("secondary_metric", "profit_factor"))

    return sorted(
        rows,
        key=lambda item: (
            not bool(item["qualified"]),
            metric_sort_value(primary_metric, float(item[primary_metric])),
            metric_sort_value(secondary_metric, float(item[secondary_metric])),
            float(item["max_drawdown_pct"]),
            -float(item["win_rate"]),
            -int(item["total_trades"]),
        ),
    )


def render_optimization_report(
    rows: list[dict[str, Any]],
    best_row: dict[str, Any],
    template: dict[str, Any],
) -> str:
    """生成中文优化汇总报告。"""
    top_n = int(template.get("output", {}).get("top_n", 10))
    top_rows = rows[:top_n]
    lines = [
        "# BTC 策略参数优化报告",
        "",
        "## 一、最优组合",
        "",
        f"- 参数编号：{best_row['candidate_id']}",
        f"- 是否通过筛选：{best_row['qualified_note']}",
        f"- 净利润：{best_row['net_profit']}",
        f"- 利润因子：{best_row['profit_factor']}",
        f"- 胜率：{best_row['win_rate']}",
        f"- 最大回撤：{best_row['max_drawdown_pct']}",
        f"- 成交笔数：{best_row['total_trades']}",
        "",
        "### 最优参数",
        "",
    ]

    best_parameters = json.loads(str(best_row["parameters_json"]))
    for key, value in best_parameters.items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(
        [
            "",
            "## 二、排名前列组合",
            "",
            "| 排名 | 编号 | 净利润 | 利润因子 | 胜率 | 最大回撤 | 成交笔数 | 结果 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )

    for index, row in enumerate(top_rows, start=1):
        lines.append(
            "| "
            f"{index} | {row['candidate_id']} | {row['net_profit']:.2f} | {row['profit_factor']:.4f} | "
            f"{row['win_rate']:.4f} | {row['max_drawdown_pct']:.4f} | {row['total_trades']} | {row['qualified_note']} |"
        )

    lines.extend(
        [
            "",
            "## 三、筛选规则",
            "",
            f"- 主排序指标：`{template.get('ranking', {}).get('primary_metric', 'net_profit')}`",
            f"- 次排序指标：`{template.get('ranking', {}).get('secondary_metric', 'profit_factor')}`",
            f"- 最少成交笔数：`{template.get('qualification', {}).get('min_trades', 1)}`",
            f"- 最大允许回撤：`{template.get('qualification', {}).get('max_drawdown_pct', 1.0)}`",
            f"- 最低利润因子：`{template.get('qualification', {}).get('min_profit_factor', 0.0)}`",
            "",
        ]
    )
    return "\n".join(lines)


def export_optimization_outputs(
    output_dir: Path,
    rows: list[dict[str, Any]],
    best_row: dict[str, Any],
    template: dict[str, Any],
    report_template_path: Path,
) -> None:
    """导出优化结果文件、最佳参数和中文模板。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(rows).to_csv(output_dir / "optimization_results.csv", index=False)
    (output_dir / "best_parameters.json").write_text(
        json.dumps(json.loads(str(best_row["parameters_json"])), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "best_summary.json").write_text(
        json.dumps(
            {
                key: value
                for key, value in best_row.items()
                if key not in {"parameters_json", "qualified", "qualified_note"}
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output_dir / "optimization_report.md").write_text(
        render_optimization_report(rows, best_row, template),
        encoding="utf-8",
    )
    (output_dir / "btc_backtest_report_template.md").write_text(
        report_template_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def build_candidate_error_row(
    candidate_id: int,
    overrides: dict[str, Any],
    initial_balance: float,
    reason: str,
) -> dict[str, Any]:
    """构造非法参数或执行失败时的兜底结果。"""
    return {
        "candidate_id": candidate_id,
        "final_balance": initial_balance,
        "net_profit": 0.0,
        "total_trades": 0,
        "win_rate": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "avg_trade": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "profit_factor": 0.0,
        "max_drawdown_pct": 1.0,
        "blocked_entries": {},
        "qualified": False,
        "qualified_note": reason,
        "parameters_json": json.dumps(overrides, ensure_ascii=False),
    }


def evaluate_btc_candidate(
    candidate_id: int,
    overrides: dict[str, Any],
    base_config: AppConfig,
    data: pd.DataFrame,
    qualification: dict[str, Any],
) -> dict[str, Any]:
    """执行单组 BTC 参数回测。"""
    config = apply_strategy_overrides(base_config, overrides)
    invalid_reason = validate_btc_parameter_set(config.strategy)
    if invalid_reason:
        return build_candidate_error_row(
            candidate_id=candidate_id,
            overrides=overrides,
            initial_balance=base_config.backtest.initial_balance,
            reason=f"参数非法: {invalid_reason}",
        )

    try:
        strategy = BtcM15RegimeStrategy(config.strategy)
        result = BacktestEngine(config, strategy).run(data)
    except Exception as exc:
        return build_candidate_error_row(
            candidate_id=candidate_id,
            overrides=overrides,
            initial_balance=base_config.backtest.initial_balance,
            reason=f"回测异常: {exc}",
        )

    summary = {key: value for key, value in result.items() if key not in {"trades", "equity_curve"}}
    qualified, qualified_note = is_candidate_qualified(summary, qualification)
    return {
        "candidate_id": candidate_id,
        **summary,
        "qualified": qualified,
        "qualified_note": qualified_note,
        "parameters_json": json.dumps(overrides, ensure_ascii=False),
    }


def run_btc_optimization(
    config_path: str | Path,
    csv_path: str | Path,
    output_dir: str | Path,
    template_path: str | None = None,
    max_workers: int | None = None,
) -> dict[str, Any]:
    """运行 BTC 参数优化，并把结果导出到指定目录。"""
    base_config = load_config(config_path)
    if base_config.strategy.name != "btc_m15_regime":
        raise ValueError("optimize-btc 仅支持 strategy.name=btc_m15_regime 的配置。")
    validate_calendar_data_source(
        base_config.news_calendar,
        base_config.safety.timezone,
        base_config.mt5.path,
    )

    template = load_optimization_template(template_path)
    report_template_path = resolve_template_path(None, DEFAULT_REPORT_TEMPLATE_PATH)
    parameter_grid = build_parameter_grid(dict(template.get("strategy_grid", {})))
    qualification = dict(template.get("qualification", {}))
    data = load_csv_history(csv_path)
    worker_count = resolve_worker_count(max_workers, len(parameter_grid))
    rows: list[dict[str, Any]] = []
    started_at = perf_counter()

    print(f"开始执行 BTC 参数优化，共 {len(parameter_grid)} 组，线程数 {worker_count}。")

    if worker_count == 1:
        for index, overrides in enumerate(parameter_grid, start=1):
            row = evaluate_btc_candidate(index, overrides, base_config, data, qualification)
            rows.append(row)
            print(f"[{len(rows)}/{len(parameter_grid)}] 参数组 {index} 已完成。")
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(
                    evaluate_btc_candidate,
                    index,
                    overrides,
                    base_config,
                    data,
                    qualification,
                ): index
                for index, overrides in enumerate(parameter_grid, start=1)
            }
            for completed_count, future in enumerate(as_completed(future_map), start=1):
                candidate_id = future_map[future]
                rows.append(future.result())
                print(f"[{completed_count}/{len(parameter_grid)}] 参数组 {candidate_id} 已完成。")

    ranked_rows = rank_candidates(rows, dict(template.get("ranking", {})))
    best_row = next((row for row in ranked_rows if row["qualified"]), ranked_rows[0])
    export_optimization_outputs(
        Path(output_dir),
        ranked_rows,
        best_row,
        template,
        report_template_path,
    )

    elapsed_seconds = perf_counter() - started_at
    return {
        "tested_candidates": len(rows),
        "qualified_candidates": sum(1 for row in rows if row["qualified"]),
        "worker_count": worker_count,
        "best_candidate_id": best_row["candidate_id"],
        "best_net_profit": best_row["net_profit"],
        "best_profit_factor": best_row["profit_factor"],
        "best_max_drawdown_pct": best_row["max_drawdown_pct"],
        "elapsed_seconds": round(elapsed_seconds, 3),
        "output_dir": str(Path(output_dir)),
    }
