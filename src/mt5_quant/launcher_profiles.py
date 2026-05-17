"""启动器预设与运行时配置管理。"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import yaml


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
    """根据预设名称获取基础配置文件路径。"""
    if profile_name not in PROFILE_PRESETS:
        raise ValueError(f"Unsupported profile: {profile_name}")
    return resolve_config_path(PROFILE_PRESETS[profile_name]["config"])


def get_runtime_profiles_dir() -> Path:
    """运行时配置副本目录。"""
    path = Path.cwd() / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_logs_dir() -> Path:
    path = Path.cwd() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_runtime_config_path(profile_name: str) -> Path:
    """按品种生成运行时配置副本路径。"""
    return get_runtime_profiles_dir() / f"{profile_name}.runtime.yaml"


def get_launch_config(profile_name: str) -> Path:
    """优先使用运行时配置副本，没有则使用基础配置。"""
    runtime_path = get_runtime_config_path(profile_name)
    if runtime_path.exists():
        return runtime_path
    return get_profile_config(profile_name)


def load_yaml_file(path: Path) -> dict[str, Any]:
    """读取 YAML 为字典。"""
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be mapping: {path}")
    return data


def load_profile_yaml(profile_name: str) -> dict[str, Any]:
    """加载当前品种用于启动的配置内容。"""
    return load_yaml_file(get_launch_config(profile_name))


def save_runtime_profile(profile_name: str, data: dict[str, Any]) -> Path:
    """保存运行时配置副本，不覆盖原始带注释配置。"""
    path = get_runtime_config_path(profile_name)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    return path
