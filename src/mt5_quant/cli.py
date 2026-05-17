"""命令行入口，负责回测与实盘模式分发。"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from mt5_quant.backtest import BacktestEngine
from mt5_quant.config import AppConfig, load_config
from mt5_quant.data import Mt5Gateway
from mt5_quant.live import LiveTradingEngine
from mt5_quant.strategy import MovingAverageAtrStrategy, XauM1MomentumStrategy


def configure_logging() -> None:
    """统一日志输出格式。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def build_strategy(config: AppConfig):
    """根据配置名称构造策略对象。"""
    if config.strategy.name == "ma_cross_atr":
        return MovingAverageAtrStrategy(config.strategy)
    if config.strategy.name == "xau_m1_momentum":
        return XauM1MomentumStrategy(config.strategy)
    raise ValueError(f"Unsupported strategy: {config.strategy.name}")


def load_csv_history(path: str | Path) -> pd.DataFrame:
    """从 CSV 读取历史 K 线。"""
    frame = pd.read_csv(path)
    required = {"time", "open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time")


def export_backtest_report(result: dict[str, object], output_dir: str | Path, config: AppConfig) -> None:
    """导出回测摘要、成交明细和净值曲线。"""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    summary = {key: value for key, value in result.items() if key not in {"trades", "equity_curve"}}
    summary["symbol"] = config.trading.symbol
    summary["timeframe"] = config.trading.timeframe
    summary["strategy"] = config.strategy.name

    if config.reporting.save_summary_json:
        (path / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    if config.reporting.save_trades_csv:
        pd.DataFrame(result["trades"]).to_csv(path / "trades.csv", index=False)
    if config.reporting.save_equity_csv:
        pd.DataFrame(result["equity_curve"]).to_csv(path / "equity_curve.csv", index=False)


def run_backtest(config: AppConfig, csv_path: str | None, bars: int | None, report_dir: str | None) -> None:
    """执行回测流程。"""
    strategy = build_strategy(config)
    if csv_path:
        data = load_csv_history(csv_path)
    else:
        gateway = Mt5Gateway(config)
        gateway.connect()
        try:
            data = gateway.get_rates(bars=bars or config.trading.history_bars)
        finally:
            gateway.shutdown()

    engine = BacktestEngine(config, strategy)
    result = engine.run(data)
    export_backtest_report(result, report_dir or config.reporting.output_dir, config)
    summary = {key: value for key, value in result.items() if key not in {"trades", "equity_curve"}}
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def run_live(config: AppConfig) -> None:
    """执行实盘或模拟盘轮询流程。"""
    strategy = build_strategy(config)
    engine = LiveTradingEngine(config, strategy)
    engine.run()


def main() -> None:
    """程序主入口。"""
    configure_logging()
    parser = argparse.ArgumentParser(description="MT5 quantitative trading system")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backtest_parser = subparsers.add_parser("backtest", help="Run a local backtest")
    backtest_parser.add_argument("--config", required=True, help="Path to yaml config")
    backtest_parser.add_argument("--csv", help="Path to CSV history file")
    backtest_parser.add_argument("--bars", type=int, help="Number of bars to fetch from MT5")
    backtest_parser.add_argument("--report-dir", help="Directory to export backtest report files")

    live_parser = subparsers.add_parser("live", help="Run live trading loop")
    live_parser.add_argument("--config", required=True, help="Path to yaml config")

    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "backtest":
        run_backtest(config, csv_path=args.csv, bars=args.bars, report_dir=args.report_dir)
        return

    if args.command == "live":
        run_live(config)
        return

    raise ValueError(f"Unhandled command: {args.command}")
