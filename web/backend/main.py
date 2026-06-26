"""XAU 策略全栈控制系统 — FastAPI 后端。

提供：
  - /api/config — 读取 / 更新 YAML 配置文件
  - /api/diagnosis — 触发信号诊断
  - /ws/signals — WebSocket 实时推送策略信号
  - JWT 认证
  - 配置变更日志
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt
import yaml
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

LOGGER = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────────────────────
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

# 配置文件目录
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "configs"))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# 诊断输出目录
DIAGNOSIS_DIR = Path(os.environ.get("DIAGNOSIS_DIR", "diagnosis_output"))
DIAGNOSIS_DIR.mkdir(parents=True, exist_ok=True)

# 配置变更日志
CHANGE_LOG = Path(os.environ.get("CHANGE_LOG", "config_changes.jsonl"))

# 允许的配置文件列表
ALLOWED_CONFIGS = list(CONFIG_DIR.glob("*.yaml")) + list(CONFIG_DIR.glob("*.yml"))

# ── FastAPI 应用 ──────────────────────────────────────────────────────
app = FastAPI(title="XAU 策略控制系统", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)

# WebSocket 连接管理
active_connections: list[WebSocket] = []


# ── 认证 ──────────────────────────────────────────────────────────────

def create_jwt_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt_token(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="缺少认证信息")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token 已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的 Token")


# ── Pydantic 模型 ────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class ConfigUpdateRequest(BaseModel):
    config_name: str
    content: dict[str, Any]


class DiagnosisRequest(BaseModel):
    config_name: str
    csv_path: str | None = None
    bars: int | None = None


# ── 辅助函数 ─────────────────────────────────────────────────────────

def _load_config_file(config_name: str) -> dict:
    path = CONFIG_DIR / config_name
    if not path.exists() or path.suffix not in {".yaml", ".yml"}:
        raise HTTPException(status_code=404, detail=f"配置文件不存在: {config_name}")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _save_config_file(config_name: str, content: dict) -> None:
    path = CONFIG_DIR / config_name
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(content, handle, default_flow_style=False, allow_unicode=True)


def _log_config_change(username: str, config_name: str, old: dict, new: dict) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "username": username,
        "config_name": config_name,
        "changes": {k: {"old": old.get(k), "new": new.get(k)} for k in new if old.get(k) != new.get(k)},
    }
    with CHANGE_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


async def _broadcast_signal(signal_data: dict) -> None:
    """向所有 WebSocket 客户端广播信号。"""
    disconnected: list[WebSocket] = []
    for connection in active_connections:
        try:
            await connection.send_json(signal_data)
        except WebSocketDisconnect:
            disconnected.append(connection)
        except Exception:
            disconnected.append(connection)
    for conn in disconnected:
        if conn in active_connections:
            active_connections.remove(conn)


# ── 路由 ─────────────────────────────────────────────────────────────

@app.post("/api/auth/login")
async def login(request: LoginRequest):
    """模拟登录，返回 JWT Token。"""
    # 生产环境应校验用户名密码
    if not request.username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    token = create_jwt_token(request.username)
    return {"access_token": token, "token_type": "bearer"}


@app.get("/api/config/list")
async def list_configs(username: str = Depends(verify_jwt_token)):
    """列出可用配置文件。"""
    files = [p.name for p in CONFIG_DIR.glob("*.yaml")] + [p.name for p in CONFIG_DIR.glob("*.yml")]
    return {"configs": sorted(files)}


@app.get("/api/config/{config_name}")
async def get_config(config_name: str, username: str = Depends(verify_jwt_token)):
    """读取指定配置文件。"""
    content = _load_config_file(config_name)
    return {"config_name": config_name, "content": content}


@app.put("/api/config/{config_name}")
async def update_config(
    config_name: str,
    request: ConfigUpdateRequest,
    username: str = Depends(verify_jwt_token),
):
    """更新指定配置文件（含备份）。"""
    old_content = _load_config_file(config_name)
    _save_config_file(config_name, request.content)
    _log_config_change(username, config_name, old_content, request.content)
    LOGGER.info("用户 %s 更新了配置 %s", username, config_name)
    return {"status": "ok", "config_name": config_name}


@app.post("/api/diagnosis/run")
async def run_diagnosis(
    request: DiagnosisRequest,
    username: str = Depends(verify_jwt_token),
):
    """运行信号诊断。"""
    from mt5_quant.diagnostics import run_signal_diagnosis

    config_path = CONFIG_DIR / request.config_name
    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"配置文件不存在: {request.config_name}")

    output_dir = DIAGNOSIS_DIR / f"{request.config_name}_{datetime.now():%Y%m%d_%H%M%S}"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = run_signal_diagnosis(
            config_path=str(config_path),
            csv_path=request.csv_path,
            bars=request.bars,
            output_dir=str(output_dir),
        )
        return {"status": "ok", "summary": result, "output_dir": str(output_dir)}
    except Exception as exc:
        LOGGER.exception("诊断失败")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/status")
async def get_status(username: str = Depends(verify_jwt_token)):
    """返回系统状态。"""
    return {
        "status": "running",
        "config_dir": str(CONFIG_DIR),
        "diagnosis_dir": str(DIAGNOSIS_DIR),
        "config_count": len(list(CONFIG_DIR.glob("*.yaml"))),
    }


# ── WebSocket ────────────────────────────────────────────────────────

@app.websocket("/ws/signals")
async def websocket_signals(websocket: WebSocket):
    """WebSocket 实时推送策略信号。"""
    await websocket.accept()
    active_connections.append(websocket)
    try:
        # 发送欢迎消息
        await websocket.send_json({"type": "connected", "message": "已连接到信号推送服务"})
        # 保持连接
        while True:
            data = await websocket.receive_text()
            # 客户端消息透传
            await websocket.send_json({"type": "echo", "data": data})
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)


# ── 启动入口 ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
