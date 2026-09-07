# -*- coding: utf-8 -*-
"""
系统信息接口模块。

提供：
    GET /api/system/info       软件与运行环境信息
    GET /api/system/stats      运行时统计
    GET /api/system/listen     监听地址与安全提示
"""

import platform
import sys

from fastapi import APIRouter

from .. import version
from ..certificate import selfsigned as cert_mod
from ..common import net_util, paths
from ..config import loader
from ..database import dao
from ..logging import logger
from . import runtime

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/addresses")
async def local_addresses():
    """返回本机全部可用网卡地址，供 RADIUS Server「报文源地址」下拉选择。"""
    return {"addresses": net_util.get_all_local_addresses()}


@router.get("/info")
async def system_info():
    """
    返回软件信息与运行环境。

    前端「系统配置」页据此展示软件名称与版本，保证前后端一致。
    """
    config = loader.load_config()
    hosts = config.get("web", {}).get("hosts") or []
    local_only = net_util.is_local_only(hosts)
    fingerprint = ""
    try:
        fingerprint = cert_mod.load_certificate_fingerprint()
    except Exception:
        fingerprint = ""
    return {
        "software_name": version.SOFTWARE_NAME,
        "software_version": version.SOFTWARE_VERSION,
        "software_description": version.SOFTWARE_DESCRIPTION,
        "frontend_version": version.FRONTEND_VERSION,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "system": platform.system(),
        "data_dir": str(paths.data_dir()),
        "log_dir": str(paths.log_dir()),
        "https_enabled": bool(config.get("web", {}).get("https")),
        "certificate_fingerprint": fingerprint,
        "listen": runtime.listen_info,
        "local_only": local_only,
    }


@router.get("/listen")
async def listen_info():
    """返回监听地址信息与安全提示。"""
    return {
        "listen": runtime.listen_info,
        "local_only": net_util.is_local_only(runtime.listen_info.get("hosts") or []),
    }


@router.get("/stats")
async def system_stats():
    """返回运行时统计信息。"""
    session = runtime.get_session()
    socket_stats = {}
    try:
        socket_stats = runtime.socket_manager.stats()
    except Exception as exc:
        logger.warning("api", "Socket 池统计获取失败", {"error": str(exc)})
    return {
        "database": dao.stats(),
        "socket_pool": socket_stats,
        "websocket_connections": runtime.ws_manager.connection_count
        if runtime.ws_manager else 0,
        "has_session": session is not None,
        "session": session.snapshot() if session is not None else None,
    }
