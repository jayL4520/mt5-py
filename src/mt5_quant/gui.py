"""图形化启动器与配置编辑器。"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

import pandas as pd

from mt5_quant import __version__
from mt5_quant.config import load_config
from mt5_quant.launcher_profiles import (
    PROFILE_PRESETS,
    get_logs_dir,
    get_runtime_profiles_dir,
    load_profile_yaml,
    save_runtime_profile,
)
from mt5_quant.news_calendar import validate_calendar_data_source
from mt5_quant.risk_overrides import (
    is_overridable_blocked_reason,
    record_blocked_reason_clear,
    record_consecutive_loss_clear,
)
from mt5_quant.runtime_events import RuntimeEventFileReader, generate_session_id


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
        self.auto_close_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="就绪")
        self.fields: list[FieldBinding] = []
        self.current_data: dict[str, Any] = {}
        self.password_visible = False
        self.password_entry: ttk.Entry | None = None
        self.password_toggle_button: ttk.Button | None = None
        self.diagnosis_running = False
        self.current_session_id: str | None = None
        self.monitor_reader = RuntimeEventFileReader()
        self.monitor_events: list[dict[str, Any]] = []
        self.monitor_rows: dict[str, dict[str, Any]] = {}
        self.monitor_session_var = tk.StringVar(value="全部会话")
        self.current_session_var = tk.StringVar(value="当前会话：未启动")
        self.monitor_tree: ttk.Treeview | None = None
        self.monitor_detail_text: tk.Text | None = None
        self.monitor_session_box: ttk.Combobox | None = None
        self.loss_clear_button: ttk.Button | None = None
        self.selected_block_clear_button: ttk.Button | None = None
        self.latest_consecutive_loss_block: dict[str, Any] | None = None
        self.selected_blocked_event: dict[str, Any] | None = None

        self._build_ui()
        self._load_profile()
        self._load_monitor_history()
        self._schedule_monitor_refresh()

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
        self.monitor_tab = ttk.Frame(notebook, padding=12)

        notebook.add(self.basic_tab, text="基础配置")
        notebook.add(self.risk_tab, text="风控配置")
        notebook.add(self.run_tab, text="启动运行")
        notebook.add(self.monitor_tab, text="运行监控")

        self._build_basic_tab()
        self._build_risk_tab()
        self._build_run_tab()
        self._build_monitor_tab()

    def _build_basic_tab(self) -> None:
        fields = [
            ("mt5", "login", "MT5 账号", int),
            ("mt5", "password", "MT5 密码", str),
            ("mt5", "server", "MT5 服务器", str),
            ("trading", "symbol", "交易品种", str),
            ("trading", "timeframe", "交易周期", str),
            ("trading", "history_bars", "历史 K 线数量", int),
            ("trading", "mt5_bar_time_shift_hours", "K 线时间修正(小时)", float),
            ("trading", "slippage_points", "允许滑点(points)", int),
            ("trading", "comment", "订单备注", str),
            ("reporting", "output_dir", "默认报表目录", str),
        ]
        self._render_fields(self.basic_tab, fields)

    def _build_risk_tab(self) -> None:
        fields = [
            ("strategy", "risk_per_trade", "单笔风险比例", float),
            ("strategy", "leverage_multiplier", "杠杆数", float),
            ("safety", "max_daily_loss_pct", "日内最大亏损比例", float),
            ("safety", "max_consecutive_losses", "连续亏损允许次数", int),
            ("safety", "trading_windows", "交易时段(逗号分隔)", list),
            ("safety", "one_direction_per_day", "日内只做一个方向", bool),
            ("safety", "trailing_stop_enabled", "启用移动止损", bool),
            ("safety", "trailing_trigger_pct", "移动止损触发比例", float),
            ("safety", "trailing_distance_pct", "移动止损跟随比例", float),
            ("news_calendar", "enabled", "启用自动新闻日历", bool),
            ("news_calendar", "provider", "新闻日历来源", str),
        ]
        self._render_fields(self.risk_tab, fields)
        override_frame = ttk.LabelFrame(self.risk_tab, text="手动风控解除", padding=8)
        override_frame.pack(fill="x", pady=(10, 0))
        ttk.Label(
            override_frame,
            text="当运行监控出现交易时段、新闻黑窗、日内亏损、连续亏损、日内单方向拦截后，可手动解除当前这类限制；不可解除缺少止损或手数为 0。",
            wraplength=720,
        ).pack(fill="x", pady=(0, 6))
        button = ttk.Button(
            override_frame,
            text="解除最近一次可解除的风控拦截，继续正常交易",
            command=self._clear_consecutive_loss_block,
            state="disabled",
        )
        button.pack(fill="x")
        self.loss_clear_button = button

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
        ttk.Checkbutton(
            top,
            text="启动后自动关闭 GUI 启动器",
            variable=self.auto_close_var,
        ).grid(row=6, column=0, sticky="w", pady=(6, 0))
        top.columnconfigure(0, weight=1)

        buttons = ttk.Frame(self.run_tab)
        buttons.pack(fill="x", pady=(12, 0))

        ttk.Button(buttons, text="保存运行配置", command=self._save_runtime_config).pack(fill="x", pady=4)
        ttk.Button(buttons, text="启动实盘 / 模拟盘", command=lambda: self._launch_process("live")).pack(fill="x", pady=4)
        ttk.Button(buttons, text="启动 MT5 历史回测", command=lambda: self._launch_process("backtest_mt5")).pack(fill="x", pady=4)
        ttk.Button(buttons, text="启动 CSV 回测", command=lambda: self._launch_process("backtest_csv")).pack(fill="x", pady=4)
        ttk.Button(buttons, text="启动 MT5 信号诊断", command=lambda: self._launch_process("diagnose_mt5")).pack(fill="x", pady=4)
        ttk.Button(buttons, text="启动 CSV 信号诊断", command=lambda: self._launch_process("diagnose_csv")).pack(fill="x", pady=4)
        ttk.Button(buttons, text="打开报表目录", command=self._open_report_dir).pack(fill="x", pady=4)
        ttk.Button(buttons, text="打开日志目录", command=self._open_logs_dir).pack(fill="x", pady=4)
        ttk.Button(buttons, text="打开运行配置目录", command=self._open_profiles_dir).pack(fill="x", pady=4)

    def _build_monitor_tab(self) -> None:
        top = ttk.Frame(self.monitor_tab)
        top.pack(fill="x", pady=(0, 10))

        ttk.Label(top, textvariable=self.current_session_var, foreground="#06c").grid(row=0, column=0, sticky="w")
        ttk.Label(top, text="会话筛选").grid(row=0, column=1, sticky="e", padx=(20, 6))
        session_box = ttk.Combobox(
            top,
            textvariable=self.monitor_session_var,
            state="readonly",
            values=["全部会话"],
            width=28,
        )
        session_box.grid(row=0, column=2, sticky="w")
        session_box.bind("<<ComboboxSelected>>", lambda _event: self._render_monitor_events())
        self.monitor_session_box = session_box
        ttk.Button(top, text="清空当前显示", command=self._clear_monitor_display).grid(row=0, column=3, padx=(10, 0))
        top.columnconfigure(0, weight=1)

        tree_frame = ttk.Frame(self.monitor_tab)
        tree_frame.pack(fill="both", expand=True)
        columns = ("time", "symbol", "timeframe", "action", "result", "reason")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=14)
        tree.heading("time", text="时间")
        tree.heading("symbol", text="品种")
        tree.heading("timeframe", text="周期")
        tree.heading("action", text="动作")
        tree.heading("result", text="结果")
        tree.heading("reason", text="原因")
        tree.column("time", width=120, anchor="w")
        tree.column("symbol", width=90, anchor="center")
        tree.column("timeframe", width=70, anchor="center")
        tree.column("action", width=80, anchor="center")
        tree.column("result", width=100, anchor="center")
        tree.column("reason", width=420, anchor="w")
        tree.tag_configure("hold", foreground="#666666")
        tree.tag_configure("blocked", background="#fff1bf")
        tree.tag_configure("success", background="#e9f7ef")
        tree.tag_configure("warning", background="#fdebd0")
        tree.tag_configure("error", background="#f8d7da")
        tree.bind("<<TreeviewSelect>>", self._on_monitor_tree_select)
        y_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        # x_scrollbar = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
        # tree.configure(yscrollcommand=y_scrollbar.set, xscrollcommand=x_scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scrollbar.grid(row=0, column=1, sticky="ns")
        # x_scrollbar.grid(row=1, column=0, sticky="ew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.monitor_tree = tree

        detail_frame = ttk.LabelFrame(self.monitor_tab, text="事件详情", padding=8)
        detail_frame.pack(fill="both", expand=False, pady=(10, 0))
        selected_clear_button = ttk.Button(
            detail_frame,
            text="解除当前选中事件的本次限制",
            command=self._clear_selected_blocked_event,
            state="disabled",
        )
        selected_clear_button.pack(fill="x", pady=(0, 6))
        self.selected_block_clear_button = selected_clear_button
        detail_text = tk.Text(detail_frame, height=10, wrap="word")
        detail_scrollbar = ttk.Scrollbar(detail_frame, orient="vertical", command=detail_text.yview)
        detail_text.configure(yscrollcommand=detail_scrollbar.set)
        detail_text.pack(side="left", fill="both", expand=True)
        detail_scrollbar.pack(side="right", fill="y")
        detail_text.configure(state="disabled")
        self.monitor_detail_text = detail_text

    def _render_fields(self, parent: ttk.Frame, field_specs: list[tuple[str, str, str, type]]) -> None:
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)

        for row, (section, key, label, caster) in enumerate(field_specs):
            ttk.Label(container, text=label).grid(row=row, column=0, sticky="w", pady=6)

            if caster is bool:
                variable: tk.Variable = tk.BooleanVar(value=False)
                widget = ttk.Checkbutton(container, variable=variable)
                widget.grid(row=row, column=1, sticky="w", pady=6)
            elif section == "mt5" and key == "password":
                variable = tk.StringVar(value="")
                password_row = ttk.Frame(container)
                password_row.grid(row=row, column=1, sticky="we", pady=6)
                widget = ttk.Entry(password_row, textvariable=variable, width=42, show="*")
                widget.pack(side="left", fill="x", expand=True)
                toggle_button = ttk.Button(
                    password_row,
                    text="👁",
                    width=4,
                    command=self._toggle_password_visibility,
                )
                toggle_button.pack(side="left", padx=(8, 0))
                self.password_entry = widget
                self.password_toggle_button = toggle_button
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
            elif binding.path == ("trading", "mt5_bar_time_shift_hours") and value is None:
                binding.variable.set("0")
            elif binding.path == ("strategy", "leverage_multiplier") and value is None:
                binding.variable.set("1.1")
            else:
                binding.variable.set("" if value is None else str(value))

        self.status_var.set(f"已加载：{PROFILE_PRESETS[profile_name]['label']}")

    def _toggle_password_visibility(self) -> None:
        """切换密码框显示或隐藏状态。"""
        if self.password_entry is None or self.password_toggle_button is None:
            return

        self.password_visible = not self.password_visible
        self.password_entry.configure(show="" if self.password_visible else "*")
        self.password_toggle_button.configure(text="🙈" if self.password_visible else "👁")

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
        session_id: str | None = generate_session_id() if mode == "live" else None
        try:
            config = load_config(runtime_path)
            if mode not in {"diagnose_mt5", "diagnose_csv"}:
                validate_calendar_data_source(
                    config.news_calendar,
                    config.safety.timezone,
                    config.mt5.path,
                )
        except Exception as exc:
            messagebox.showerror("启动前检查失败", str(exc))
            self.status_var.set("启动前检查失败。")
            return

        if mode in {"diagnose_mt5", "diagnose_csv"}:
            self._run_diagnosis_async(runtime_path, mode)
            return

        command = self._build_launch_command(runtime_path, mode, session_id=session_id)

        try:
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            subprocess.Popen(command, cwd=Path.cwd(), creationflags=creationflags)
        except Exception as exc:
            messagebox.showerror("启动失败", str(exc))
            return

        if mode == "live" and session_id is not None:
            self.current_session_id = session_id
            self.current_session_var.set(f"当前会话：{session_id}")
            self._refresh_monitor_session_options()
        self.status_var.set("已启动新进程。")
        if self.auto_close_var.get():
            self.root.after(100, self.root.destroy)
            return
        messagebox.showinfo("已启动", "已启动新的运行进程。")

    def _run_diagnosis_async(self, runtime_path: Path, mode: str) -> None:
        """在后台线程里执行信号诊断，并在 GUI 内弹出摘要。"""
        if self.diagnosis_running:
            messagebox.showinfo("诊断进行中", "当前已有一个诊断任务正在运行，请等待完成。")
            return

        csv_path: str | None = None
        bars: int | None = None
        source = "mt5"
        if mode == "diagnose_csv":
            csv_path = self.csv_path_var.get().strip()
            if not csv_path:
                messagebox.showerror("启动失败", "请先选择 CSV 文件。")
                return
            source = "csv"
        else:
            bars = int(self.current_data.get("trading", {}).get("history_bars", 1000))

        output_dir = self._get_diagnosis_output_dir(source)
        self.diagnosis_running = True
        self.status_var.set("正在执行信号诊断，请稍候...")

        worker = threading.Thread(
            target=self._diagnosis_worker,
            args=(runtime_path, csv_path, bars, output_dir),
            daemon=True,
        )
        worker.start()

    def _diagnosis_worker(
        self,
        runtime_path: Path,
        csv_path: str | None,
        bars: int | None,
        output_dir: Path,
    ) -> None:
        """后台执行诊断，避免阻塞 GUI 主线程。"""
        try:
            from mt5_quant.diagnostics import run_signal_diagnosis

            summary = run_signal_diagnosis(
                config_path=runtime_path,
                csv_path=csv_path,
                bars=bars,
                output_dir=output_dir,
            )
        except Exception as exc:
            self.root.after(0, lambda: self._on_diagnosis_failed(exc))
            return

        self.root.after(0, lambda: self._on_diagnosis_completed(summary, output_dir))

    def _on_diagnosis_failed(self, exc: Exception) -> None:
        """诊断失败后的 GUI 回调。"""
        self.diagnosis_running = False
        self.status_var.set("信号诊断失败。")
        messagebox.showerror("信号诊断失败", str(exc))

    def _on_diagnosis_completed(self, summary: dict[str, Any], output_dir: Path) -> None:
        """诊断完成后在 GUI 中展示摘要。"""
        self.diagnosis_running = False
        self.status_var.set("信号诊断完成。")
        messagebox.showinfo("信号诊断完成", self._format_diagnosis_summary(summary, output_dir))

    @staticmethod
    def _format_diagnosis_summary(summary: dict[str, Any], output_dir: Path) -> str:
        """把诊断结果整理成适合弹窗查看的中文摘要。"""
        blocked_entries = summary.get("blocked_entries", {})
        conclusions = summary.get("diagnosis_conclusions", [])
        lines = [
            f"品种：{summary.get('symbol', '')}",
            f"周期：{summary.get('timeframe', '')}",
            f"样本数量：{summary.get('bars', 0)}",
            f"原始入场信号数：{summary.get('raw_entry_signal_count', 0)}",
            f"回测成交数：{summary.get('total_trades', 0)}",
            f"样本周期匹配：{summary.get('interval_matches_config', False)}",
            f"财经日历状态：{summary.get('calendar_status', '')}",
            f"拦截统计：{blocked_entries if blocked_entries else '无'}",
            "",
            "诊断结论：",
        ]
        for item in conclusions[:4]:
            lines.append(f"- {item}")
        lines.extend(
            [
                "",
                f"报告目录：{output_dir}",
                "可继续查看 diagnosis_summary.json 和 diagnosis_report.md。",
            ]
        )
        return "\n".join(lines)

    def _build_launch_command(self, runtime_path: Path, mode: str, session_id: str | None = None) -> list[str]:
        if getattr(sys, "frozen", False):
            base = [sys.executable]
        else:
            base = [sys.executable, str(Path(__file__).resolve().with_name("cli.py"))]

        if mode == "live":
            command = base + ["live", "--config", str(runtime_path)]
            if session_id:
                command.extend(["--session-id", session_id])
            return command

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

        if mode == "diagnose_mt5":
            bars_value = self.current_data.get("trading", {}).get("history_bars", 1000)
            return base + [
                "diagnose-signals",
                "--config",
                str(runtime_path),
                "--bars",
                str(bars_value),
                "--output-dir",
                str(self._get_diagnosis_output_dir("mt5")),
            ]

        if mode == "diagnose_csv":
            csv_path = self.csv_path_var.get().strip()
            if not csv_path:
                raise ValueError("请先选择 CSV 文件。")
            return base + [
                "diagnose-signals",
                "--config",
                str(runtime_path),
                "--csv",
                csv_path,
                "--output-dir",
                str(self._get_diagnosis_output_dir("csv")),
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
        self._open_directory(get_runtime_profiles_dir())

    def _open_report_dir(self) -> None:
        self._open_directory(self._get_effective_report_dir())

    def _open_logs_dir(self) -> None:
        self._open_directory(get_logs_dir())

    def _get_effective_report_dir(self) -> Path:
        report_dir = self.report_dir_var.get().strip() or self.current_data.get("reporting", {}).get("output_dir", "reports")
        path = Path(report_dir)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _get_diagnosis_output_dir(self, source: str) -> Path:
        """返回 GUI 信号诊断输出目录。"""
        profile_name = self.profile_var.get()
        path = self._get_effective_report_dir() / f"diagnosis_{profile_name}_{source}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _load_monitor_history(self) -> None:
        """加载当天累计事件历史。"""
        self.monitor_events = self.monitor_reader.load_today_events()
        self._refresh_monitor_session_options()
        self._render_monitor_events()

    def _schedule_monitor_refresh(self) -> None:
        """按固定间隔轮询当天新增事件。"""
        self.root.after(1000, self._poll_monitor_events)

    def _poll_monitor_events(self) -> None:
        """增量读取当天事件文件的新增内容。"""
        try:
            new_events = self.monitor_reader.read_available_events()
        except Exception:
            new_events = []
        if new_events:
            self.monitor_events.extend(new_events)
            self._refresh_monitor_session_options()
            self._render_monitor_events()
        self._schedule_monitor_refresh()

    def _refresh_monitor_session_options(self) -> None:
        """刷新会话筛选下拉框。"""
        if self.monitor_tree is None:
            return
        session_values = ["全部会话"]
        seen: set[str] = set()
        if self.current_session_id:
            session_values.append(self.current_session_id)
            seen.add(self.current_session_id)
        for event in self.monitor_events:
            session_id = str(event.get("session_id", "")).strip()
            if session_id and session_id not in seen:
                session_values.append(session_id)
                seen.add(session_id)
        current = self.monitor_session_var.get()
        if current not in session_values:
            self.monitor_session_var.set("全部会话")
        if self.monitor_session_box is not None:
            self.monitor_session_box.configure(values=session_values)

    def _render_monitor_events(self) -> None:
        """根据当前筛选条件重绘运行事件列表。"""
        if self.monitor_tree is None:
            return
        selected_session = self.monitor_session_var.get()
        self.monitor_rows.clear()
        for item_id in self.monitor_tree.get_children():
            self.monitor_tree.delete(item_id)

        for index, event in enumerate(self._filtered_monitor_events()):
            item_id = f"event-{index}"
            self.monitor_rows[item_id] = event
            self.monitor_tree.insert(
                "",
                "end",
                iid=item_id,
                values=(
                    self._format_monitor_time(event),
                    str(event.get("symbol", "")),
                    str(event.get("timeframe", "")),
                    self._format_monitor_action(event),
                    self._format_monitor_result(event),
                    str(event.get("message", "")),
                ),
                tags=(self._monitor_row_tag(event),),
            )

        if selected_session == "全部会话" and self.current_session_id:
            self.current_session_var.set(f"当前会话：{self.current_session_id}")
        self._update_loss_clear_button_state()

    def _filtered_monitor_events(self) -> list[dict[str, Any]]:
        """返回会话筛选后的事件列表。"""
        selected_session = self.monitor_session_var.get()
        if selected_session == "全部会话":
            events = self.monitor_events
        else:
            events = [item for item in self.monitor_events if str(item.get("session_id", "")) == selected_session]
        return sorted(events, key=self._monitor_sort_key, reverse=True)

    def _update_loss_clear_button_state(self) -> None:
        """运行监控发现可解除拦截后，允许用户从风控页一键解除最近一次。"""
        self.latest_consecutive_loss_block = self._find_latest_overridable_block()
        if self.loss_clear_button is None:
            return
        if self.latest_consecutive_loss_block is None:
            self.loss_clear_button.configure(
                state="disabled",
                text="解除最近一次可解除的风控拦截，继续正常交易",
            )
            return
        reason = str(self.latest_consecutive_loss_block.get("blocked_reason", ""))
        self.loss_clear_button.configure(
            state="normal",
            text=f"解除最近一次 {reason} 拦截，继续正常交易",
        )

    def _find_latest_overridable_block(self) -> dict[str, Any] | None:
        """找到当前筛选范围内最近一次允许手动解除的 signal_blocked 事件。"""
        for event in self._filtered_monitor_events():
            if self._can_clear_blocked_event(event):
                return event
        return None

    def _can_clear_blocked_event(self, event: dict[str, Any]) -> bool:
        """只有真正的风控/配置拦截允许手动解除。"""
        if str(event.get("event_type", "")) != "signal_blocked":
            return False
        return is_overridable_blocked_reason(str(event.get("blocked_reason", "")))

    def _clear_consecutive_loss_block(self) -> None:
        """兼容风控页按钮：解除最近一次可解除拦截。"""
        self._clear_blocked_event(self.latest_consecutive_loss_block)

    def _clear_selected_blocked_event(self) -> None:
        """解除运行监控详情里当前选中的拦截事件。"""
        self._clear_blocked_event(self.selected_blocked_event)

    def _clear_blocked_event(self, event: dict[str, Any] | None) -> None:
        """写入手动解除指令，实盘进程下一轮读取后生效。"""
        if event is None:
            messagebox.showinfo("无需解除", "当前没有选中可解除的风控拦截。")
            return
        if not self._can_clear_blocked_event(event):
            messagebox.showerror("不能解除", "该事件不是可手动解除的风控/配置拦截。")
            return

        extra = event.get("extra", {})
        if not isinstance(extra, dict):
            extra = {}
        symbol = str(event.get("symbol", "") or self.current_data.get("trading", {}).get("symbol", "")).strip()
        if not symbol:
            messagebox.showerror("解除失败", "无法识别交易品种。")
            return
        try:
            magic_number = int(extra.get("magic_number", self.current_data.get("trading", {}).get("magic_number", 0)))
        except (TypeError, ValueError):
            magic_number = 0
        if magic_number <= 0:
            messagebox.showerror("解除失败", "无法识别策略魔术号。")
            return

        blocked_reason = str(event.get("blocked_reason", ""))
        timezone_name = str(self.current_data.get("safety", {}).get("timezone", "Asia/Shanghai"))
        day_key = self._resolve_event_day_key(event, timezone_name)
        if blocked_reason == "consecutive_loss_limit_reached":
            try:
                consecutive_losses = int(extra.get("consecutive_losses", 0))
            except (TypeError, ValueError):
                consecutive_losses = 0
            if consecutive_losses <= 0:
                messagebox.showerror("解除失败", "事件里没有有效的连续亏损次数，无法生成解除指令。")
                return
            record = record_consecutive_loss_clear(
                symbol=symbol,
                magic_number=magic_number,
                day_key=day_key,
                consecutive_losses=consecutive_losses,
                session_id=str(event.get("session_id", "")),
            )
        else:
            record = record_blocked_reason_clear(
                symbol=symbol,
                magic_number=magic_number,
                day_key=day_key,
                blocked_reason=blocked_reason,
                session_id=str(event.get("session_id", "")),
                extra={"source_event_bar_time": event.get("bar_time", "")},
            )

        self.status_var.set("已写入风控拦截解除指令。")
        messagebox.showinfo(
            "已解除本次限制",
            "已写入解除指令，实盘进程下一根新 K 线处理时生效。\n"
            f"品种：{record['symbol']}\n"
            f"交易日：{record['day_key']}\n"
            f"拦截原因：{blocked_reason}",
        )

    @staticmethod
    def _resolve_event_day_key(event: dict[str, Any], timezone_name: str) -> str:
        """按事件 K 线时间计算本地交易日，和实盘风控的 day_key 保持一致。"""
        timestamp = str(event.get("bar_time", "") or event.get("timestamp", ""))
        try:
            parsed = pd.Timestamp(timestamp)
            if parsed.tzinfo is None:
                parsed = parsed.tz_localize("UTC")
            return parsed.tz_convert(timezone_name).strftime("%Y-%m-%d")
        except Exception:
            return pd.Timestamp.now(tz=timezone_name).strftime("%Y-%m-%d")

    def _clear_monitor_display(self) -> None:
        """清空当前 GUI 中已显示的事件，不删除底层文件。"""
        self.monitor_events = []
        self.monitor_rows.clear()
        if self.monitor_tree is not None:
            for item_id in self.monitor_tree.get_children():
                self.monitor_tree.delete(item_id)
        self._set_monitor_detail("")
        self.selected_blocked_event = None
        if self.selected_block_clear_button is not None:
            self.selected_block_clear_button.configure(
                state="disabled",
                text="解除当前选中事件的本次限制",
            )
        self._refresh_monitor_session_options()
        self._update_loss_clear_button_state()

    def _on_monitor_tree_select(self, _event=None) -> None:
        """点击事件行时展示详情。"""
        if self.monitor_tree is None:
            return
        selected = self.monitor_tree.selection()
        if not selected:
            return
        event = self.monitor_rows.get(selected[0], {})
        self.selected_blocked_event = event if self._can_clear_blocked_event(event) else None
        if self.selected_block_clear_button is not None:
            if self.selected_blocked_event is None:
                self.selected_block_clear_button.configure(
                    state="disabled",
                    text="解除当前选中事件的本次限制",
                )
            else:
                reason = str(event.get("blocked_reason", ""))
                self.selected_block_clear_button.configure(
                    state="normal",
                    text=f"解除当前选中的 {reason} 限制",
                )
        self._set_monitor_detail(self._format_monitor_detail(event))

    def _set_monitor_detail(self, content: str) -> None:
        """更新事件详情文本框。"""
        if self.monitor_detail_text is None:
            return
        self.monitor_detail_text.configure(state="normal")
        self.monitor_detail_text.delete("1.0", tk.END)
        self.monitor_detail_text.insert("1.0", content)
        self.monitor_detail_text.configure(state="disabled")

    @staticmethod
    def _format_monitor_action(event: dict[str, Any]) -> str:
        action = str(event.get("signal_action", "")).strip()
        if action == "buy":
            return "买入"
        if action == "sell":
            return "卖出"
        if action == "close":
            return "平仓"
        if action == "hold":
            return "无动作"
        return action or "-"

    @staticmethod
    def _format_monitor_result(event: dict[str, Any]) -> str:
        event_type = str(event.get("event_type", ""))
        mapping = {
            "signal_hold": "无动作",
            "signal_blocked": "被拦截",
            "signal_ignored": "被忽略",
            "signal_open_attempt": "尝试开仓",
            "position_opened": "已开仓",
            "position_closed": "已平仓",
            "position_stop_updated": "已更新止损",
            "news_windows_refreshed": "已刷新新闻黑窗",
            "runtime_warning": "警告",
            "runtime_error": "错误",
        }
        return mapping.get(event_type, event_type or "-")

    def _format_monitor_time(self, event: dict[str, Any]) -> str:
        timestamp = str(event.get("timestamp", ""))
        try:
            local_time = pd.Timestamp(timestamp).tz_convert("Asia/Shanghai").strftime("%H:%M:%S")
        except Exception:
            local_time = timestamp
        if self.current_session_id and str(event.get("session_id", "")) == self.current_session_id:
            return f"★ {local_time}"
        return local_time

    @staticmethod
    def _monitor_row_tag(event: dict[str, Any]) -> str:
        event_type = str(event.get("event_type", ""))
        if event_type == "signal_hold":
            return "hold"
        if event_type in {"signal_blocked", "signal_ignored"}:
            return "blocked"
        if event_type in {"position_opened", "position_closed", "position_stop_updated", "signal_open_attempt"}:
            return "success"
        if event_type == "runtime_warning":
            return "warning"
        if event_type == "runtime_error":
            return "error"
        return ""

    @staticmethod
    def _monitor_sort_key(event: dict[str, Any]) -> tuple[int, str]:
        timestamp = str(event.get("timestamp", ""))
        try:
            parsed = pd.Timestamp(timestamp)
            return (1, parsed.isoformat())
        except Exception:
            return (0, timestamp)

    @staticmethod
    def _format_monitor_detail(event: dict[str, Any]) -> str:
        detail = {
            "时间": event.get("timestamp", ""),
            "会话ID": event.get("session_id", ""),
            "品种": event.get("symbol", ""),
            "周期": event.get("timeframe", ""),
            "策略": event.get("strategy", ""),
            "事件类型": event.get("event_type", ""),
            "动作": event.get("signal_action", ""),
            "信号原因": event.get("signal_reason", ""),
            "拦截原因": event.get("blocked_reason", ""),
            "K线时间": event.get("bar_time", ""),
            "持仓方向": event.get("position_side", ""),
            "说明": event.get("message", ""),
            "附加信息": event.get("extra", {}),
        }
        return json.dumps(detail, indent=2, ensure_ascii=False)

    def _open_directory(self, path: Path) -> None:
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
