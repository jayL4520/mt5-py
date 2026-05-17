"""命令行入口与多品种启动菜单。"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

import pandas as pd

from mt5_quant import __version__
from mt5_quant.backtest import BacktestEngine
from mt5_quant.config import AppConfig, load_config
from mt5_quant.data import Mt5Gateway
from mt5_quant.live import LiveTradingEngine
from mt5_quant.strategy import BtcM15RegimeStrategy, MovingAverageAtrStrategy, XauM1MomentumStrategy


PROFILE_PRESETS = {
    "xau": {
        "label": "黄金 XAUUSD / M1",
        "config": "config.xauusd.m1.yaml",
    },
    "btc": {
        "label": "比特币 BTCUSD / M15",
        "config": "config.btcusd.m15.yaml",
    },
}


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
    if config.strategy.name == "btc_m15_regime":
        return BtcM15RegimeStrategy(config.strategy)
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


def resolve_runtime_root() -> Path:
    """解析当前运行时根目录，兼容源码和打包 exe。"""
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[2]


def resolve_config_path(config_name: str) -> Path:
    """优先读取当前目录配置，读不到再回退到打包内置配置。"""
    cwd_path = Path.cwd() / config_name
    if cwd_path.exists():
        return cwd_path

    runtime_path = resolve_runtime_root() / config_name
    if runtime_path.exists():
        return runtime_path

    raise FileNotFoundError(f"Config file not found: {config_name}")


def get_profile_config(profile_name: str) -> Path:
    """根据预设名称获取配置文件路径。"""
    if profile_name not in PROFILE_PRESETS:
        raise ValueError(f"Unsupported profile: {profile_name}")
    return resolve_config_path(PROFILE_PRESETS[profile_name]["config"])


def prompt_choice(title: str, options: list[tuple[str, str]]) -> str:
    """显示简单文本菜单并返回用户选择。"""
    print()
    print(title)
    for key, label in options:
        print(f"  {key}. {label}")

    valid = {key for key, _ in options}
    while True:
        value = input("请输入选项编号: ").strip().lower()
        if value in valid:
            return value
        print("输入无效，请重新输入。")


def prompt_text(prompt: str, default: str = "") -> str:
    """读取文本输入，回车时使用默认值。"""
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def run_launcher() -> None:
    """无参数时进入多品种切换启动器。"""
    print(f"MT5 量化交易系统 v{__version__}")
    print("启动模式：多品种切换启动器")

    profile_key = prompt_choice(
        "请选择要运行的品种：",
        [
            ("1", PROFILE_PRESETS["xau"]["label"]),
            ("2", PROFILE_PRESETS["btc"]["label"]),
            ("q", "退出"),
        ],
    )
    if profile_key == "q":
        print("已退出。")
        return

    profile_name = "xau" if profile_key == "1" else "btc"
    config_path = get_profile_config(profile_name)
    config = load_config(config_path)

    mode = prompt_choice(
        "请选择运行模式：",
        [
            ("1", "实盘 / 模拟盘运行"),
            ("2", "MT5 历史数据回测"),
            ("3", "CSV 数据回测"),
            ("q", "退出"),
        ],
    )
    if mode == "q":
        print("已退出。")
        return

    print()
    print(f"当前品种：{config.trading.symbol}")
    print(f"当前周期：{config.trading.timeframe}")
    print(f"当前策略：{config.strategy.name}")
    print(f"配置文件：{config_path}")

    if mode == "1":
        print("即将进入实盘 / 模拟盘轮询模式。")
        run_live(config)
        return

    if mode == "2":
        bars_text = prompt_text("请输入回测 K 线数量", str(config.trading.history_bars))
        report_dir = prompt_text("请输入报表输出目录", config.reporting.output_dir)
        run_backtest(config, csv_path=None, bars=int(bars_text), report_dir=report_dir)
        return

    csv_path = prompt_text("请输入 CSV 文件路径")
    report_dir = prompt_text("请输入报表输出目录", config.reporting.output_dir)
    run_backtest(config, csv_path=csv_path, bars=None, report_dir=report_dir)


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(description=f"MT5 quantitative trading system v{__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backtest_parser = subparsers.add_parser("backtest", help="Run a local backtest")
    backtest_parser.add_argument("--config", required=True, help="Path to yaml config")
    backtest_parser.add_argument("--csv", help="Path to CSV history file")
    backtest_parser.add_argument("--bars", type=int, help="Number of bars to fetch from MT5")
    backtest_parser.add_argument("--report-dir", help="Directory to export backtest report files")

    live_parser = subparsers.add_parser("live", help="Run live trading loop")
    live_parser.add_argument("--config", required=True, help="Path to yaml config")

    launcher_parser = subparsers.add_parser("launch", help="Open the interactive launcher menu")
    launcher_parser.add_argument("--profile", choices=["xau", "btc"], help="Preset profile to start")
    launcher_parser.add_argument("--mode", choices=["live", "backtest"], help="Run mode")
    launcher_parser.add_argument("--bars", type=int, help="Bars used for MT5 history backtest")
    launcher_parser.add_argument("--csv", help="CSV path used for CSV backtest")
    launcher_parser.add_argument("--report-dir", help="Directory to export backtest report files")

    return parser


def run_launch_command(args) -> None:
    """支持命令行方式直接指定预设品种。"""
    if not args.profile or not args.mode:
        run_launcher()
        return

    config = load_config(get_profile_config(args.profile))
    if args.mode == "live":
        run_live(config)
        return

    run_backtest(config, csv_path=args.csv, bars=args.bars, report_dir=args.report_dir)


def main() -> None:
    """程序主入口。"""
    configure_logging()

    if len(sys.argv) == 1:
        run_launcher()
        return

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "launch":
        run_launch_command(args)
        return

    config = load_config(args.config)

    if args.command == "backtest":
        run_backtest(config, csv_path=args.csv, bars=args.bars, report_dir=args.report_dir)
        return

    if args.command == "live":
        run_live(config)
        return

    raise ValueError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    main()
