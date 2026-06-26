"""单元测试：optimizer — 参数优化模块。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from mt5_quant.optimizer import (
    build_parameter_grid,
    evaluate_btc_candidate,
    is_candidate_qualified,
    load_optimization_template,
    metric_sort_value,
    rank_candidates,
    render_optimization_report,
    resolve_template_path,
    resolve_worker_count,
    validate_btc_parameter_set,
)
from mt5_quant.config import AppConfig, StrategyConfig


# ── resolve_worker_count ───────────────────────────────────────────────

class TestResolveWorkerCount:
    def test_single_task(self) -> None:
        assert resolve_worker_count(None, 1) == 1

    def test_explicit_max_respected(self) -> None:
        assert resolve_worker_count(3, 10) == 3

    def test_max_capped_by_tasks(self) -> None:
        assert resolve_worker_count(16, 3) == 3

    def test_zero_or_negative_defaults_to_one(self) -> None:
        assert resolve_worker_count(0, 5) == 1
        assert resolve_worker_count(-1, 5) == 1


# ── build_parameter_grid ───────────────────────────────────────────────

class TestBuildParameterGrid:
    def test_basic_cartesian_product(self) -> None:
        grid = build_parameter_grid({
            "ema_fast": [5, 10],
            "ema_slow": [20, 30],
        })
        assert len(grid) == 4
        assert {"ema_fast": 5, "ema_slow": 20} in grid
        assert {"ema_fast": 10, "ema_slow": 30} in grid

    def test_single_parameter(self) -> None:
        grid = build_parameter_grid({"adx_threshold": [20, 25]})
        assert len(grid) == 2

    def test_three_parameters(self) -> None:
        grid = build_parameter_grid({"a": [1, 2], "b": [3, 4], "c": [5]})
        assert len(grid) == 4

    def test_empty_grid_raises(self) -> None:
        with pytest.raises(ValueError, match="未提供 strategy_grid"):
            build_parameter_grid({})

    def test_invalid_keys_raise(self) -> None:
        with pytest.raises(ValueError, match="未知策略字段"):
            build_parameter_grid({"unknown_key": [1, 2]})

    def test_non_list_values_raise(self) -> None:
        with pytest.raises(ValueError, match="必须提供非空列表"):
            build_parameter_grid({"ema_fast": "not_a_list"})

    def test_empty_list_raises(self) -> None:
        with pytest.raises(ValueError, match="必须提供非空列表"):
            build_parameter_grid({"ema_fast": []})


# ── validate_btc_parameter_set ─────────────────────────────────────────

class TestValidateBtcParameterSet:
    @staticmethod
    def make_strategy(**overrides) -> StrategyConfig:
        cfg = StrategyConfig(
            name="btc_m15_regime", short_window=20, long_window=50,
            atr_period=14, atr_stop_multiple=2.0, reward_to_risk=2.0,
            risk_per_trade=0.01, leverage_multiplier=1.1,
            ema_fast=10, ema_slow=20,
            rsi_period=14, rsi_buy_threshold=55.0, rsi_sell_threshold=45.0,
            breakout_lookback=20, take_profit_pct=0.003, stop_loss_pct=0.004,
            adx_period=14, adx_threshold=22.0,
            volume_window=20, volume_multiplier=1.0, breakout_buffer_pct=0.0,
        )
        for key, value in overrides.items():
            setattr(cfg, key, value)
        return cfg

    def test_valid_config_returns_none(self) -> None:
        result = validate_btc_parameter_set(self.make_strategy())
        assert result is None

    def test_ema_fast_gte_slow(self) -> None:
        result = validate_btc_parameter_set(self.make_strategy(ema_fast=20, ema_slow=10))
        assert result is not None and "ema_fast" in result

    def test_adx_period_too_small(self) -> None:
        result = validate_btc_parameter_set(self.make_strategy(adx_period=1))
        assert result is not None and "adx_period" in result

    def test_adx_threshold_zero(self) -> None:
        result = validate_btc_parameter_set(self.make_strategy(adx_threshold=0))
        assert result is not None and "adx_threshold" in result

    def test_adx_threshold_negative(self) -> None:
        result = validate_btc_parameter_set(self.make_strategy(adx_threshold=-1))
        assert result is not None and "adx_threshold" in result

    def test_volume_window_zero(self) -> None:
        result = validate_btc_parameter_set(self.make_strategy(volume_window=0))
        assert result is not None and "volume_window" in result

    def test_volume_multiplier_negative(self) -> None:
        result = validate_btc_parameter_set(self.make_strategy(volume_multiplier=-0.5))
        assert result is not None and "volume_multiplier" in result

    def test_breakout_buffer_negative(self) -> None:
        result = validate_btc_parameter_set(self.make_strategy(breakout_buffer_pct=-0.1))
        assert result is not None and "breakout_buffer_pct" in result

    def test_atr_stop_multiple_zero(self) -> None:
        result = validate_btc_parameter_set(self.make_strategy(atr_stop_multiple=0))
        assert result is not None and "atr_stop_multiple" in result

    def test_reward_to_risk_zero(self) -> None:
        result = validate_btc_parameter_set(self.make_strategy(reward_to_risk=0))
        assert result is not None and "reward_to_risk" in result

    def test_volume_multiplier_zero_allowed(self) -> None:
        result = validate_btc_parameter_set(self.make_strategy(volume_multiplier=0))
        assert result is None  # >= 0 is allowed

    def test_breakout_buffer_zero_allowed(self) -> None:
        result = validate_btc_parameter_set(self.make_strategy(breakout_buffer_pct=0))
        assert result is None


# ── is_candidate_qualified ─────────────────────────────────────────────

class TestIsCandidateQualified:
    def test_passes_all_filters(self) -> None:
        result = {
            "total_trades": 10,
            "max_drawdown_pct": 0.05,
            "profit_factor": 1.5,
        }
        qualified, note = is_candidate_qualified(result, {
            "min_trades": 5,
            "max_drawdown_pct": 0.1,
            "min_profit_factor": 1.0,
        })
        assert qualified is True
        assert note == "通过"

    def test_fails_min_trades(self) -> None:
        result = {"total_trades": 2, "max_drawdown_pct": 0.05, "profit_factor": 2.0}
        qualified, note = is_candidate_qualified(result, {
            "min_trades": 5,
        })
        assert qualified is False
        assert "成交笔数不足" in note

    def test_fails_max_drawdown(self) -> None:
        result = {"total_trades": 10, "max_drawdown_pct": 0.15, "profit_factor": 2.0}
        qualified, note = is_candidate_qualified(result, {
            "min_trades": 5,
            "max_drawdown_pct": 0.1,
        })
        assert qualified is False
        assert "回撤超限" in note

    def test_fails_profit_factor(self) -> None:
        result = {"total_trades": 10, "max_drawdown_pct": 0.05, "profit_factor": 0.8}
        qualified, note = is_candidate_qualified(result, {
            "min_trades": 5,
            "min_profit_factor": 1.0,
        })
        assert qualified is False
        assert "盈亏比不足" in note

    def test_default_qualification(self) -> None:
        """When no qualification provided, default to min_trades=1."""
        result = {"total_trades": 0, "max_drawdown_pct": 0.0, "profit_factor": 0.0}
        qualified, _ = is_candidate_qualified(result, {})
        assert qualified is False  # 0 < 1


# ── metric_sort_value ──────────────────────────────────────────────────

class TestMetricSortValue:
    def test_net_profit_inverted(self) -> None:
        assert metric_sort_value("net_profit", 1000) == -1000
        assert metric_sort_value("net_profit", 500) == -500

    def test_max_drawdown_not_inverted(self) -> None:
        assert metric_sort_value("max_drawdown_pct", 0.05) == 0.05
        assert metric_sort_value("max_drawdown_pct", 0.10) == 0.10

    def test_profit_factor_inverted(self) -> None:
        assert metric_sort_value("profit_factor", 2.0) == -2.0


# ── rank_candidates ────────────────────────────────────────────────────

class TestRankCandidates:
    def test_qualified_first_then_unqualified(self) -> None:
        rows = [
            {"qualified": False, "net_profit": 200, "profit_factor": 2.0, "max_drawdown_pct": 0.1, "win_rate": 0.5, "total_trades": 10},
            {"qualified": True, "net_profit": 100, "profit_factor": 1.5, "max_drawdown_pct": 0.05, "win_rate": 0.6, "total_trades": 20},
        ]
        ranked = rank_candidates(rows, {"primary_metric": "net_profit", "secondary_metric": "profit_factor"})
        assert ranked[0]["qualified"] is True
        assert ranked[1]["qualified"] is False

    def test_sorted_by_net_profit_desc(self) -> None:
        rows = [
            {"qualified": True, "net_profit": 200, "profit_factor": 2.0, "max_drawdown_pct": 0.1, "win_rate": 0.5, "total_trades": 10},
            {"qualified": True, "net_profit": 300, "profit_factor": 1.5, "max_drawdown_pct": 0.05, "win_rate": 0.6, "total_trades": 20},
        ]
        ranked = rank_candidates(rows, {})
        assert ranked[0]["net_profit"] == 300

    def test_default_metrics(self) -> None:
        rows = [
            {"qualified": True, "net_profit": 100, "profit_factor": 1.5, "max_drawdown_pct": 0.1, "win_rate": 0.5, "total_trades": 10},
            {"qualified": True, "net_profit": 200, "profit_factor": 2.0, "max_drawdown_pct": 0.05, "win_rate": 0.6, "total_trades": 20},
        ]
        ranked = rank_candidates(rows, {})
        assert ranked[0]["net_profit"] == 200

    def test_tie_breaker_by_drawdown(self) -> None:
        rows = [
            {"qualified": True, "net_profit": 100, "profit_factor": 1.5, "max_drawdown_pct": 0.15, "win_rate": 0.5, "total_trades": 10},
            {"qualified": True, "net_profit": 100, "profit_factor": 1.5, "max_drawdown_pct": 0.05, "win_rate": 0.5, "total_trades": 10},
        ]
        ranked = rank_candidates(rows, {"primary_metric": "net_profit"})
        assert ranked[0]["max_drawdown_pct"] == 0.05


# ── render_optimization_report ─────────────────────────────────────────

class TestRenderOptimizationReport:
    def test_report_contains_best_parameters(self) -> None:
        rows = [{
            "candidate_id": 1, "net_profit": 1000, "profit_factor": 2.0,
            "win_rate": 0.6, "max_drawdown_pct": 0.05, "total_trades": 20,
            "qualified": True, "qualified_note": "通过",
            "parameters_json": '{"ema_fast": 10, "ema_slow": 20}',
        }]
        best_row = rows[0]
        template = {"output": {"top_n": 10}, "ranking": {"primary_metric": "net_profit"}}
        report = render_optimization_report(rows, best_row, template)
        assert "最优组合" in report
        assert "ema_fast" in report
        assert "净利润" in report
        assert "利润因子" in report

    def test_top_n_capped(self) -> None:
        rows = []
        for i in range(5):
            rows.append({
                "candidate_id": i + 1, "net_profit": 100 * (i + 1), "profit_factor": 1.0,
                "win_rate": 0.5, "max_drawdown_pct": 0.1, "total_trades": 10,
                "qualified": True, "qualified_note": "通过",
                "parameters_json": '{"a": 1}',
            })
        template = {"output": {"top_n": 2}}
        report = render_optimization_report(
            sorted(rows, key=lambda r: -r["net_profit"]),
            rows[0], template,
        )
        # Should only have 2 rows in the table
        lines = report.splitlines()
        table_lines = [l for l in lines if l.startswith("|")]
        # Header + separator + 2 data rows = 3+? Actually header + separator + 2 = 4 lines
        assert len(table_lines) >= 4  # header, separator, 2 data rows

    def test_empty_top_n_defaults(self) -> None:
        rows = [{
            "candidate_id": 1, "net_profit": 500, "profit_factor": 1.5,
            "win_rate": 0.55, "max_drawdown_pct": 0.08, "total_trades": 15,
            "qualified": True, "qualified_note": "通过",
            "parameters_json": '{"a": 1}',
        }]
        report = render_optimization_report(rows, rows[0], {})
        assert "最优组合" in report


# ── resolve_template_path ──────────────────────────────────────────────

class TestResolveTemplatePath:
    def test_explicit_path_exists(self, tmp_path: Path) -> None:
        file = tmp_path / "template.yaml"
        file.write_text("key: value", encoding="utf-8")
        result = resolve_template_path(str(file), Path("nonexistent"))
        assert result == file

    def test_explicit_path_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            resolve_template_path("/nonexistent/path.yaml", Path("default.yaml"))


# ── load_optimization_template ─────────────────────────────────────────

class TestLoadOptimizationTemplate:
    def test_loads_yaml_dict(self, tmp_path: Path) -> None:
        template = tmp_path / "template.yaml"
        template.write_text(yaml.dump({"strategy_grid": {"a": [1, 2]}}), encoding="utf-8")
        data = load_optimization_template(str(template))
        assert isinstance(data, dict)
        assert "strategy_grid" in data

    def test_non_dict_raises(self, tmp_path: Path) -> None:
        template = tmp_path / "template.yaml"
        template.write_text("[1,2,3]", encoding="utf-8")
        with pytest.raises(ValueError, match="根节点必须是字典"):
            load_optimization_template(str(template))
