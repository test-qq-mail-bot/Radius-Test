# -*- coding: utf-8 -*-
"""
测试任务接口模块。

提供：
    GET  /api/tasks/current        当前测试会话快照
    POST /api/tasks                启动测试
    POST /api/tasks/{task_id}/stop 停止测试
    POST /api/tasks/heartbeat      前端心跳

安全机制（项目书 26）：
    启动需前端二次确认（确认动作在前端完成，本接口只负责执行）；
    停止按钮触发后立即取消全部在途任务。
"""

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from ..config import defaults, loader
from ..logging import logger
from ..testing import state as state_mod
from ..testing.session import TestSession
from . import runtime
from .api_user import _load_users

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _resolve_users(usernames: List[str]) -> List[tuple]:
    """
    根据用户名列表解析出 (用户名, 密码) 列表。

    参数：
        usernames: 用户名列表，空列表表示全部启用用户
    """
    users = _load_users()
    if not usernames:
        return [(u["username"], u["password"]) for u in users]
    mapping = {u["username"]: u["password"] for u in users}
    result = []
    missing = []
    for name in usernames:
        if name in mapping:
            result.append((name, mapping[name]))
        else:
            missing.append(name)
    if missing:
        raise HTTPException(status_code=400, detail="用户不存在：%s" % "、".join(missing[:5]))
    return result


@router.get("/current")
async def current_task():
    """返回当前测试会话快照。"""
    session = runtime.get_session()
    if session is None:
        return {"has_session": False, "session": None}
    return {"has_session": True, "session": session.snapshot()}


@router.post("")
async def start_task(payload: Dict[str, Any]):
    """
    启动测试任务。

    请求体：
        {
          "server_name": "server1",
          "usernames": ["test001"],
          "protocol": "pap",
          "rate": 10,
          "concurrency": 10000,
          "save_packets": false,
          "enable_accounting": true
        }
    """
    existing = runtime.get_session()
    if existing is not None and existing.running:
        raise HTTPException(status_code=400, detail="已有测试正在运行，请先停止")

    server_name = str(payload.get("server_name") or "").strip()
    if not server_name:
        raise HTTPException(status_code=400, detail="必须指定 RADIUS Server")
    server = None
    for item in loader.get_servers():
        if item.get("name") == server_name:
            server = item
            break
    if server is None:
        raise HTTPException(status_code=404, detail="RADIUS Server 不存在")
    if not server.get("enabled", True):
        raise HTTPException(status_code=400, detail="该 RADIUS Server 已停用")

    protocol = str(payload.get("protocol") or server.get("protocol") or "pap").lower()
    if protocol not in defaults.SUPPORTED_PROTOCOLS:
        raise HTTPException(status_code=400, detail="不支持的认证协议")

    usernames = payload.get("usernames") or []
    users = _resolve_users([str(u) for u in usernames])
    if not users:
        raise HTTPException(status_code=400, detail="没有可用的测试用户")

    config = loader.load_config()
    options = {
        "server_name": server_name,
        "protocol": protocol,
        "users": users,
        "rate": float(payload.get("rate") or config["test"]["rate"]),
        "concurrency": int(payload.get("concurrency") or config["test"]["max_concurrency"]),
        "save_packets": bool(payload.get(
            "save_packets", config["storage"]["save_packets"])),
        "enable_accounting": bool(payload.get("enable_accounting", True)),
        "interim_interval": int(config["test"]["interim_interval"]),
        "interim_max_fail": int(config["test"]["interim_max_fail"]),
        "peer_challenge_bytes": int(config["radius"]["mschap_peer_challenge_bytes"]),
        "online_criteria": str(
            payload.get("online_criteria")
            or config["test"].get("online_criteria")
            or "accounting"),
    }
    if options["online_criteria"] not in ("accounting", "auth"):
        raise HTTPException(status_code=400, detail="在线判定依据非法，可选 accounting / auth")
    if options["rate"] <= 0:
        raise HTTPException(status_code=400, detail="测试速率必须大于 0")
    if options["concurrency"] <= 0:
        raise HTTPException(status_code=400, detail="并发数必须大于 0")

    async def broadcast(data: dict) -> None:
        if runtime.ws_manager is not None:
            await runtime.ws_manager.broadcast({"type": "test_progress", "data": data})

    session = TestSession(options, broadcast=broadcast,
                          socket_manager=runtime.socket_manager)
    runtime.set_session(session)
    await session.start()
    logger.info("api", "测试任务已通过接口启动", {
        "task_id": session.task_id,
        "server": server_name,
        "protocol": protocol,
        "users": len(users),
    })
    return {
        "success": True,
        "task_id": session.task_id,
        "session": session.snapshot(),
    }


@router.post("/heartbeat")
async def heartbeat():
    """前端心跳，用于维持测试存活状态。"""
    session = runtime.get_session()
    if session is not None:
        session.heartbeat()
    return {"success": True}


@router.post("/{task_id}/stop")
async def stop_task(task_id: str):
    """停止指定测试任务。"""
    session = runtime.get_session()
    if session is None or session.task_id != task_id:
        raise HTTPException(status_code=404, detail="测试任务不存在")
    if not session.running:
        return {"success": True, "message": "测试已结束", "session": session.snapshot()}
    await session.stop(state_mod.USER_STOP)
    snapshot = session.snapshot()
    runtime.clear_session()
    logger.info("api", "测试任务已通过接口停止", {"task_id": task_id})
    return {"success": True, "message": "已终止", "session": snapshot}
