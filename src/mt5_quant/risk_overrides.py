"""手动风控解除指令文件。

GUI 和实盘进程是两个独立进程，因此这里用 logs/risk-overrides.json 做轻量通信。
解除指令按品种、魔术号、本地交易日和拦截原因隔离，避免不同策略互相影响。
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from mt5_quant.launcher_profiles import get_logs_dir


OVERRIDE_FILE_NAME = "risk-overrides.json"
OVERRIDABLE_BLOCKED_REASONS = {
    "outside_trading_window",
    "news_blackout_window",
    "daily_loss_limit_reached",
    "consecutive_loss_limit_reached",
    "one_direction_per_day",
}


def get_risk_override_path(base_dir: Path | None = None) -> Path:
    """返回风控解除指令文件路径。"""
    directory = base_dir or get_logs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / OVERRIDE_FILE_NAME


def build_override_key(symbol: str, magic_number: int, day_key: str) -> str:
    """用交易品种、魔术号、本地交易日组成唯一键，避免不同策略互相影响。"""
    return f"{symbol}|{magic_number}|{day_key}"


def build_block_override_key(symbol: str, magic_number: int, day_key: str, blocked_reason: str) -> str:
    """把具体拦截原因也放进 key，支持只解除当前这一类限制。"""
    return f"{build_override_key(symbol, magic_number, day_key)}|{blocked_reason}"


def is_overridable_blocked_reason(blocked_reason: str) -> bool:
    """判断某个拦截原因是否允许手动解除。"""
    return blocked_reason in OVERRIDABLE_BLOCKED_REASONS


def record_blocked_reason_clear(
    *,
    symbol: str,
    magic_number: int,
    day_key: str,
    blocked_reason: str,
    session_id: str = "",
    extra: dict[str, Any] | None = None,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """记录一次手动解除某个拦截原因的指令。"""
    if not is_overridable_blocked_reason(blocked_reason):
        raise ValueError(f"Blocked reason cannot be manually cleared: {blocked_reason}")

    path = get_risk_override_path(base_dir)
    data = _load_override_file(path)
    record = {
        "symbol": symbol,
        "magic_number": magic_number,
        "day_key": day_key,
        "blocked_reason": blocked_reason,
        "session_id": session_id,
        "extra": extra or {},
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    data[build_block_override_key(symbol, magic_number, day_key, blocked_reason)] = record
    _write_override_file(path, data)
    return record


def get_blocked_reason_clear(
    *,
    symbol: str,
    magic_number: int,
    day_key: str,
    blocked_reason: str,
    base_dir: Path | None = None,
) -> dict[str, Any] | None:
    """读取某个拦截原因的手动解除记录。"""
    path = get_risk_override_path(base_dir)
    data = _load_override_file(path)
    record = data.get(build_block_override_key(symbol, magic_number, day_key, blocked_reason))
    return record if isinstance(record, dict) else None


def is_blocked_reason_cleared(
    *,
    symbol: str,
    magic_number: int,
    day_key: str,
    blocked_reason: str,
    base_dir: Path | None = None,
) -> bool:
    """判断某个拦截原因当天是否已被手动解除。"""
    return get_blocked_reason_clear(
        symbol=symbol,
        magic_number=magic_number,
        day_key=day_key,
        blocked_reason=blocked_reason,
        base_dir=base_dir,
    ) is not None


def record_consecutive_loss_clear(
    *,
    symbol: str,
    magic_number: int,
    day_key: str,
    consecutive_losses: int,
    session_id: str = "",
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """记录一次手动解除连续亏损熔断。

    consecutive_losses 表示“本次已确认解除到的连续亏损次数”。如果之后亏损次数继续增加，
    实盘进程会再次触发 consecutive_loss_limit_reached。
    """
    path = get_risk_override_path(base_dir)
    data = _load_override_file(path)
    key = build_override_key(symbol, magic_number, day_key)
    record = {
        "symbol": symbol,
        "magic_number": magic_number,
        "day_key": day_key,
        "cleared_consecutive_losses": int(consecutive_losses),
        "session_id": session_id,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    data[key] = record
    data[build_block_override_key(symbol, magic_number, day_key, "consecutive_loss_limit_reached")] = {
        **record,
        "blocked_reason": "consecutive_loss_limit_reached",
        "extra": {"cleared_consecutive_losses": int(consecutive_losses)},
    }
    _write_override_file(path, data)
    return record


def get_cleared_consecutive_losses(
    *,
    symbol: str,
    magic_number: int,
    day_key: str,
    base_dir: Path | None = None,
) -> int:
    """读取当前品种当天已手动解除到的连续亏损次数。"""
    path = get_risk_override_path(base_dir)
    data = _load_override_file(path)
    record = data.get(
        build_block_override_key(symbol, magic_number, day_key, "consecutive_loss_limit_reached"),
        data.get(build_override_key(symbol, magic_number, day_key), {}),
    )
    if not isinstance(record, dict):
        return 0
    try:
        return max(0, int(record.get("cleared_consecutive_losses", 0)))
    except (TypeError, ValueError):
        return 0


def _load_override_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_override_file(path: Path, data: dict[str, Any]) -> None:
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)
