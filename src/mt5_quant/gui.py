"""图形化启动器与配置编辑器。"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from mt5_quant import __version__
from mt5_quant.launcher_profiles import (
    PROFILE_PRESETS,
    get_launch_config,
    get_runtime_profiles_dir,
    load_profile_yaml,
    save_runtime_profile,
)


@dataclass(slots=True)
class FieldBinding:
    """单个表单字段绑定。"""

    path: tuple[str, ...]
    variable: tk.Variable
    caster: type


def launch_gui_application() -> None:
    """启动图形化窗口。"""
    _hide_console_window()
    app = LauncherWindow()
    app.run()


def _hide_console_window() -> None:
    """在 GUI 模式下隐藏控制台窗口。"""
    if sys.platform != "win32":
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        return


class LauncherWindow:
    """多品种图形启动器。"""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"MT5 量化交易系统 {__version__}")
        self.root.geometry("820x700")
        self.root.minsize(820, 700)

        self.profile_var = tk.StringVar(value="xau")
        self.report_dir_var = tk.StringVar(value="")
        self.csv_path_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="就绪")
        self.fields: list[FieldBinding] = []
        self.current_data: dict[str, Any] = {}

        self._build_ui()
        self._load_profile()

    def run(self) -> None:
        """进入窗口主循环。"""
        self.root.mainloop()

    def _build_ui(self) -> None:
        header = ttk.Frame(self.root, padding=12)
        header.pack(fill="x")

        ttk.Label(header, text="品种预设", font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        profile_box = ttk.Combobox(
            header,
            textvariable=self.profile_var,
            values=[key for key in PROFILE_PRESETS],
            state="readonly",
            width=14,
        )
        profile_box.pack(side="left", padx=8)
        profile_box.bind("<<ComboboxSelected>>", lambda _event: self._load_profile())

        ttk.Label(header, textvariable=self.status_var, foreground="#0a5").pack(side="right")

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self.basic_tab = ttk.Frame(notebook, padding=12)
        self.risk_tab = ttk.Frame(notebook, padding=12)
        self.run_tab = ttk.Frame(notebook, padding=12)

        notebook.add(self.basic_tab, text="基础配置")
        notebook.add(self.risk_tab, text="风控配置")
        notebook.add(self.run_tab, text="启动运行")

        self._build_basic_tab()
        self._build_risk_tab()
        self._build_run_tab()

    def _build_basic_tab(self) -> None:
        fields = [
            ("mt5", "login", "MT5 账号", int),
            ("mt5", "password", "MT5 密码", str),
            ("mt5", "server", "MT5 服务器", str),
            ("trading", "symbol", "交易品种", str),
            ("trading", "timeframe", "交易周期", str),
            ("trading", "history_bars", "历史 K 线数量", int),
            ("trading", "slippage_points", "允许滑点(points)", int),
            ("trading", "comment", "订单备注", str),
            ("reporting", "output_dir", "默认报表目录", str),
        ]
        self._render_fields(self.basic_tab, fields)

    def _build_risk_tab(self) -> None:
        fields = [
            ("strategy", "risk_per_trade", "单笔风险比例", float),
            ("safety", "max_daily_loss_pct", "日内最大亏损比例", float),
            ("safety", "max_consecutive_losses", "连续亏损熔断次数", int),
            ("safety", "trading_windows", "交易时段(逗号分隔)", list),
            ("safety", "one_direction_per_day", "日内只做一个方向", bool),
            ("safety", "trailing_stop_enabled", "启用移动止损", bool),
            ("safety", "trailing_trigger_pct", "移动止损触发比例", float),
            ("safety", "trailing_distance_pct", "移动止损跟随比例", float),
            ("news_calendar", "enabled", "启用自动新闻日历", bool),
            ("news_calendar", "provider", "新闻日历来源", str),
        ]
        self._render_fields(self.risk_tab, fields)

    def _build_run_tab(self) -> None:
        top = ttk.Frame(self.run_tab)
        top.pack(fill="x", pady=(0, 10))

        ttk.Label(top, text="当前启动配置会先保存到运行副本：").grid(row=0, column=0, sticky="w")
        self.runtime_path_label = ttk.Label(top, text="", foreground="#06c")
        self.runtime_path_label.grid(row=1, column=0, sticky="w", pady=(4, 10))

        ttk.Label(top, text="CSV 回测文件").grid(row=2, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.csv_path_var, width=70).grid(row=3, column=0, sticky="we", pady=(4, 8))
        ttk.Button(top, text="选择 CSV", command=self._choose_csv).grid(row=3, column=1, padx=(8, 0))

        ttk.Label(top, text="报表输出目录").grid(row=4, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.report_dir_var, width=70).grid(row=5, column=0, sticky="we", pady=(4, 8))
        ttk.Button(top, text="选择目录", command=self._choose_report_dir).grid(row=5, column=1, padx=(8, 0))
        top.columnconfigure(0, weight=1)

        buttons = ttk.Frame(self.run_tab)
        buttons.pack(fill="x", pady=(12, 0))

        ttk.Button(buttons, text="保存运行配置", command=self._save_runtime_config).pack(fill="x", pady=4)
        ttk.Button(buttons, text="启动实盘 / 模拟盘", command=lambda: self._launch_process("live")).pack(fill="x", pady=4)
        ttk.Button(buttons, text="启动 MT5 历史回测", command=lambda: self._launch_process("backtest_mt5")).pack(fill="x", pady=4)
        ttk.Button(buttons, text="启动 CSV 回测", command=lambda: self._launch_process("backtest_csv")).pack(fill="x", pady=4)
        ttk.Button(buttons, text="打开运行配置目录", command=self._open_profiles_dir).pack(fill="x", pady=4)

    def _render_fields(self, parent: ttk.Frame, field_specs: list[tuple[str, str, str, type]]) -> None:
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)

        for row, (section, key, label, caster) in enumerate(field_specs):
            ttk.Label(container, text=label).grid(row=row, column=0, sticky="w", pady=6)

            if caster is bool:
                variable: tk.Variable = tk.BooleanVar(value=False)
                widget = ttk.Checkbutton(container, variable=variable)
                widget.grid(row=row, column=1, sticky="w", pady=6)
            else:
                variable = tk.StringVar(value="")
                widget = ttk.Entry(container, textvariable=variable, width=48)
                widget.grid(row=row, column=1, sticky="we", pady=6)

            container.columnconfigure(1, weight=1)
            self.fields.append(FieldBinding(path=(section, key), variable=variable, caster=caster))

    def _load_profile(self) -> None:
        profile_name = self.profile_var.get()
        self.current_data = load_profile_yaml(profile_name)
        self.report_dir_var.set(self.current_data.get("reporting", {}).get("output_dir", ""))
        self.csv_path_var.set("")
        self.runtime_path_label.configure(text=str(get_runtime_profiles_dir() / f"{profile_name}.runtime.yaml"))

        for binding in self.fields:
            value = self._get_nested_value(self.current_data, binding.path)
            if binding.caster is bool:
                binding.variable.set(bool(value))
            elif binding.caster is list:
                if isinstance(value, list):
                    binding.variable.set(", ".join(str(item) for item in value))
                else:
                    binding.variable.set(str(value or ""))
            else:
                binding.variable.set("" if value is None else str(value))

        self.status_var.set(f"已加载：{PROFILE_PRESETS[profile_name]['label']}")

    def _save_runtime_config(self) -> Path:
        profile_name = self.profile_var.get()
        data = load_profile_yaml(profile_name)

        for binding in self.fields:
            self._set_nested_value(data, binding.path, self._coerce_value(binding))

        data.setdefault("reporting", {})["output_dir"] = self.report_dir_var.get().strip() or data["reporting"].get("output_dir", "")
        self.current_data = data
        runtime_path = save_runtime_profile(profile_name, data)
        self.status_var.set(f"已保存运行配置：{runtime_path.name}")
        return runtime_path

    def _launch_process(self, mode: str) -> None:
        runtime_path = self._save_runtime_config()
        command = self._build_launch_command(runtime_path, mode)

        try:
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            subprocess.Popen(command, cwd=Path.cwd(), creationflags=creationflags)
        except Exception as exc:
            messagebox.showerror("启动失败", str(exc))
            return

        self.status_var.set("已启动新进程。")
        messagebox.showinfo("已启动", "已启动新的运行进程。")

    def _build_launch_command(self, runtime_path: Path, mode: str) -> list[str]:
        if getattr(sys, "frozen", False):
            base = [sys.executable]
        else:
            base = [sys.executable, str(Path(__file__).resolve().with_name("cli.py"))]

        if mode == "live":
            return base + ["live", "--config", str(runtime_path)]

        if mode == "backtest_mt5":
            bars_value = self.current_data.get("trading", {}).get("history_bars", 1000)
            return base + [
                "backtest",
                "--config",
                str(runtime_path),
                "--bars",
                str(bars_value),
                "--report-dir",
                self.report_dir_var.get().strip() or self.current_data.get("reporting", {}).get("output_dir", ""),
            ]

        csv_path = self.csv_path_var.get().strip()
        if not csv_path:
            raise ValueError("请先选择 CSV 文件。")
        return base + [
            "backtest",
            "--config",
            str(runtime_path),
            "--csv",
            csv_path,
            "--report-dir",
            self.report_dir_var.get().strip() or self.current_data.get("reporting", {}).get("output_dir", ""),
        ]

    def _choose_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 CSV 回测文件",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
        )
        if path:
            self.csv_path_var.set(path)

    def _choose_report_dir(self) -> None:
        path = filedialog.askdirectory(title="选择报表输出目录")
        if path:
            self.report_dir_var.set(path)

    def _open_profiles_dir(self) -> None:
        path = get_runtime_profiles_dir()
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(path)])
            else:
                messagebox.showinfo("目录位置", str(path))
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def _coerce_value(self, binding: FieldBinding) -> Any:
        if binding.caster is bool:
            return bool(binding.variable.get())
        if binding.caster is int:
            return int(str(binding.variable.get()).strip())
        if binding.caster is float:
            return float(str(binding.variable.get()).strip())
        if binding.caster is list:
            raw = str(binding.variable.get()).strip()
            return [item.strip() for item in raw.split(",") if item.strip()]
        return str(binding.variable.get()).strip()

    @staticmethod
    def _get_nested_value(data: dict[str, Any], path: tuple[str, ...]) -> Any:
        current: Any = data
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    @staticmethod
    def _set_nested_value(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
        current = data
        for key in path[:-1]:
            current = current.setdefault(key, {})
        current[path[-1]] = value
