# -*- coding: utf-8 -*-
"""
测试任务接口模块。

提供：
    GET  /api/tasks/current        当前测试会话快照
    POST /api/tasks                启动测试
    POST /api/tasks/{task_id}/stop 停止测试
    POST /api/tasks/heartbeat      测试页面心跳（存活上报）
    POST /api/tasks/leave          测试页面离开（立即中断）

安全机制（项目书 26）：
    启动需前端二次确认（确认动作在前端完成，本接口只负责执行）；
    停止按钮触发后立即取消全部在途任务。

    测试存活判据（需求5）：唯一依据是「前端是否仍停在测试页面」，
    由 web.page_liveness 维护，两条通路——
        1. 测试页面每 2 秒调用 /heartbeat 上报，超过 4 秒未上报即中断；
        2. 应用内跳到非测试页面时立即中断（POST /leave 或由心跳上报的页面判定）。
    窗口切到后台不算离开页面，测试继续运行。
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from ..config import defaults, loader
from ..logging import logger
from ..radius import builder as radius_builder
from ..testing import state as state_mod
from ..testing.session import TestSession
from . import page_liveness
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


def _normalize_dot1x(raw) -> Optional[dict]:
    """
    规范化前端传入的 Dot1X 接入配置。

    返回 None 表示未配置（沿用报文构造的原硬编码属性）。
    NAS-Port 与 Service-Type 做前置校验，避免运行期解析抛错。

    字段：
        access_type: wired / wireless
        ssid: 仅无线使用，留空由报文构造置为 Radius-Test
        nas_port: NAS-Port(5) 端口号，数值，留空则每用户随机或按序号分配
        nas_port_id: NAS-Port-Id(87) 端口名称，字符串
        calling_station_id: 终端 MAC
        nas_identifier / service_type / framed_ip_address / connect_info: 常用参数
    """
    if not isinstance(raw, dict):
        return None
    access_type = str(raw.get("access_type") or "wired").lower()
    if access_type not in ("wired", "wireless"):
        access_type = "wired"

    nas_port = str(raw.get("nas_port") or "").strip()
    if nas_port and (not nas_port.isdigit() or not 1 <= int(nas_port) <= 65535):
        raise HTTPException(status_code=400, detail="NAS-Port 需为 1~65535 的整数")

    service_type = str(raw.get("service_type") or "").strip()
    if service_type and not service_type.isdigit():
        from ..radius import builder as radius_builder
        if service_type.lower() not in radius_builder.SERVICE_TYPES:
            raise HTTPException(status_code=400, detail="Service-Type 取值非法")

    return {
        "access_type": access_type,
        "ssid": str(raw.get("ssid") or "").strip(),
        "nas_port": nas_port,
        "nas_port_id": str(raw.get("nas_port_id") or "").strip(),
        "calling_station_id": str(raw.get("calling_station_id") or "").strip(),
        "nas_identifier": str(raw.get("nas_identifier") or "").strip(),
        "service_type": service_type,
        "framed_ip_address": str(raw.get("framed_ip_address") or "").strip(),
        "connect_info": str(raw.get("connect_info") or "").strip(),
    }


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
          "enable_accounting": true,
          "dot1x": {
              "access_type": "wired",
              "ssid": "",
              "nas_port": "",
              "nas_port_id": "",
              "calling_station_id": "",
              "nas_identifier": "",
              "service_type": "",
              "framed_ip_address": "",
              "connect_info": ""
          }
        }

    说明：
        dot1x 可选；未提供时沿用报文构造的原硬编码属性。
        提供后同时作用于认证报文与计费报文（含 Interim-Update / Stop），
        使服务端看到的接入属性前后一致。
    """
    existing = runtime.get_session()
    if existing is not None and existing.running:
        raise HTTPException(status_code=400, detail="已有测试正在运行，请先停止")
    # 互斥（需求3/5）：账号认证测试进行中不允许启动性能测试
    if runtime.user_test_count() > 0:
        raise HTTPException(status_code=400, detail="账号认证测试正在运行，请先停止后再启动性能测试")

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
    # 每个 Server 可单独配置「计费间隔」；为 0 时沿用全局 test.interim_interval
    server_interval = int(server.get("accounting_interval") or 0)
    interim_interval = server_interval if server_interval > 0 \
        else int(config["test"]["interim_interval"])
    options = {
        "server_name": server_name,
        "protocol": protocol,
        "users": users,
        "rate": float(payload.get("rate") or config["test"]["rate"]),
        "concurrency": int(payload.get("concurrency") or config["test"]["max_concurrency"]),
        "save_packets": bool(payload.get(
            "save_packets", config["storage"]["save_packets"])),
        "enable_accounting": bool(payload.get("enable_accounting", True)),
        "interim_interval": interim_interval,
        "interim_max_fail": int(config["test"]["interim_max_fail"]),
        "peer_challenge_bytes": int(config["radius"]["mschap_peer_challenge_bytes"]),
        "online_criteria": str(
            payload.get("online_criteria")
            or config["test"].get("online_criteria")
            or "accounting"),
        "accounting_timeout": float(config["test"].get("accounting_timeout") or 1.0),
        "accounting_retry_count": int(config["test"].get("accounting_retry_count") or 1),
        "accounting_message_authenticator": bool(
            config["test"].get("accounting_message_authenticator")),
        "packet_trace_limit": int(config.get("log", {}).get("packet_trace_limit") or 0),
        # 可选：Dot1X 接入配置，同时作用于认证与计费报文。
        # 任务级只补齐「设备级」默认值（NAS-Identifier / Connect-Info）；
        # 端口与终端级字段（NAS-Port / NAS-Port-Id / 终端 MAC）留空时，
        # 由 TestSession._user_dot1x 在派发给每个用户时按序号唯一生成，
        # 两处都走 builder 的同一套口径，不存在各写一套字段白名单的情况。
        "dot1x": radius_builder.resolve_device_fields(
            _normalize_dot1x(payload.get("dot1x")),
        ),
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
async def heartbeat(payload: Optional[Dict[str, Any]] = None):
    """
    测试页面心跳，用于维持「前端仍停在测试页面」的存活状态。

    请求体：
        {"page": "perf" | "server" | 其他页面标识}

    说明（需求5）：
        只有测试页面（perf / Radius 用户测试 server）的会上报刷新存活时间；
        上报的是非测试页面且此前有测试页面上报过，则视为已离开测试页面，
        立即中断测试（PAGE_LEFT），不再等到超时。
    """
    page = str((payload or {}).get("page") or "")
    outcome = page_liveness.report(page)
    if outcome == "left":
        await page_liveness.stop_all_tests(state_mod.PAGE_LEFT)
    return {"success": True, "page": page, "alive": outcome != "left"}


@router.post("/leave")
async def leave(payload: Optional[Dict[str, Any]] = None):
    """
    测试页面离开通知：立即中断测试（需求5）。

    请求体：
        {"page": "result"}

    说明：
        用于前端在应用内跳转离开测试页面时主动声明，
        与心跳上报非测试页面效果一致；无测试在跑时为空操作。
    """
    page = str((payload or {}).get("page") or "")
    if page_liveness.activated():
        page_liveness.mark_left(page)
        await page_liveness.stop_all_tests(state_mod.PAGE_LEFT)
    return {"success": True, "page": page}


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
