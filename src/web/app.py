# -*- coding: utf-8 -*-
"""
FastAPI 应用装配模块。

职责：
    1. 装配全部 API 路由与 WebSocket 端点；
    2. 挂载内置静态资源与页面模板；
    3. 保证程序完全离线可运行（禁止运行时从互联网加载任何资源）。

说明：
    项目不使用模板引擎，页面由单个 HTML 外壳 + 内置 JS 渲染，
    从而避免引入额外第三方依赖。
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import asyncio

from .. import version
from ..common import paths
from ..logging import logger
from . import (
    api_config,
    api_dictionary,
    api_result,
    api_server,
    api_system,
    api_task,
    api_user,
)
from . import runtime
from . import page_liveness
from .ws import WebSocketManager


def _web_root():
    """返回 Web 资源根目录（兼容源码运行与打包运行）。"""
    builtin = paths.builtin_web_dir()
    if builtin.is_dir():
        return builtin
    return paths.web_dir()


def create_app() -> FastAPI:
    """
    创建并返回 FastAPI 应用实例。

    返回：
        FastAPI 应用对象。
    """
    app = FastAPI(
        title=version.SOFTWARE_NAME,
        version=version.SOFTWARE_VERSION,
        description=version.SOFTWARE_DESCRIPTION,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # WebSocket 管理器依赖测试会话提供者
    manager = WebSocketManager(session_provider=runtime.get_session)
    runtime.set_ws_manager(manager)

    app.include_router(api_system.router)
    app.include_router(api_config.router)
    app.include_router(api_server.router)
    app.include_router(api_user.router)
    app.include_router(api_dictionary.router)
    app.include_router(api_task.router)
    app.include_router(api_result.router)

    web_root = _web_root()
    static_dir = web_root / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        """返回单页应用外壳。"""
        index_file = web_root / "templates" / "index.html"
        if not index_file.is_file():
            return JSONResponse(status_code=404, content={"detail": "页面文件缺失"})
        return FileResponse(str(index_file))

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon():
        """返回站点图标。"""
        icon = static_dir / "svg" / "logo.svg"
        if icon.is_file():
            return FileResponse(str(icon), media_type="image/svg+xml")
        return JSONResponse(status_code=404, content={"detail": "not found"})

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket 端点：实时测试数据与心跳。"""
        await manager.connect(websocket)
        try:
            while True:
                text = await websocket.receive_text()
                await manager.handle_message(websocket, text)
        except WebSocketDisconnect:
            await manager.disconnect(websocket)
        except Exception as exc:
            logger.warning("websocket", "连接异常", {"error": str(exc)})
            await manager.disconnect(websocket)

    @app.on_event("startup")
    async def on_startup():
        """应用启动：开启连接保活、测试页面存活看门狗与 Disconnect-Request 监听。"""
        await manager.start_monitor()
        await page_liveness.start_watch()
        _install_loop_exception_handler()
        _log_radius_environment()
        await _start_disconnect_listener()
        logger.info("web", "Web 应用已启动", {
            "software": "%s %s" % (version.SOFTWARE_NAME, version.SOFTWARE_VERSION),
        })
        logger.debug("web", "调试日志已启用，WebSocket 断连噪声已抑制", {})


    @app.on_event("shutdown")
    async def on_shutdown():
        """应用停止：停止连接保活、页面看门狗、Disconnect 监听并关闭连接。"""
        session = runtime.get_session()
        if session is not None and session.running:
            from ..testing import state as state_mod

            await session.stop(state_mod.SYSTEM_ERROR)
        listener = runtime.get_disconnect_listener()
        if listener is not None:
            listener.stop()
        await page_liveness.stop_watch()
        await manager.stop_monitor()
        await manager.close_all()

    return app


def _log_radius_environment() -> None:
    """
    输出 RADIUS 运行环境摘要（DEBUG 级）。

    排查强制下线时，第一个要确认的问题是「服务端会把 Disconnect-Request 发到哪个地址」：
    服务端通常以报文源地址（或 NAS-IP-Address 属性）作为 NAS 地址。
    因此这里把每个已启用 Server 的 NAS-IP-Address 生效值、报文源地址配置与本机可用
    IPv4 一并打出，便于拿到日志后直接比对。
    """
    if not logger.is_debug_enabled():
        return
    from ..config import loader
    from ..radius.disconnect import local_ipv4_candidates

    servers = [s for s in loader.get_servers() if s.get("enabled", True)]
    if not servers:
        logger.debug("radius", "尚未配置可用的 RADIUS Server", {})
        return
    for server in servers:
        target = str(server.get("authentication_server_address")
                     or server.get("server_address") or "")
        account_target = str(server.get("accounting_server_address") or target)
        nas_ip = str(server.get("nas_ip_address") or "").strip()
        source = str(server.get("source_address") or "").strip()
        logger.debug("radius", "RADIUS 运行环境摘要", {
            "server": str(server.get("name") or target),
            "auth_target": "%s:%s" % (target, server.get("authentication_port") or 1812),
            "acct_target": "%s:%s" % (account_target, server.get("accounting_port") or 1813),
            "nas_ip_address": nas_ip or "(未配置：服务端只能依据报文源地址识别 NAS)",
            "source_address": source or "(未指定：由系统路由选择)",
            "local_ipv4": ",".join(local_ipv4_candidates(target)) or "(未知)",
        })


async def _start_disconnect_listener() -> None:
    """
    启动 Disconnect-Request 监听（RFC 5176，需求4）。

    密钥来源：全部已启用 RADIUS Server 的通用 / 认证 / 计费密钥，逐个尝试校验，
    任一命中即视为合法请求（服务端不同实现使用的密钥字段可能不同）。

    监听失败（例如 3799 已被同机的 RADIUS 服务器占用）只记录日志并降级运行，
    认证与计费功能不受影响。
    """
    from ..config import loader
    from ..radius.disconnect import DISCONNECT_PORT, DisconnectListener

    options = (loader.load_config().get("test") or {}).get("disconnect_listener") or {}

    # 用第一个已启用 Server 的地址推导本机出口地址，便于优先绑定正确的网卡
    probe_host = ""
    for server in loader.get_servers():
        if not server.get("enabled", True):
            continue
        probe_host = str(server.get("authentication_server_address")
                         or server.get("server_address") or "").strip()
        if probe_host:
            break

    listener = DisconnectListener(
        port=int(options.get("port") or DISCONNECT_PORT),
        enabled=bool(options.get("enabled", True)),
        probe_host=probe_host,
    )

    def secret_candidates():
        """汇总所有候选共享密钥（去重），供逐个校验。"""
        items = []
        seen = set()
        for server in loader.get_servers():
            if not server.get("enabled", True):
                continue
            name = str(server.get("name") or server.get("server_address") or "")
            for field in ("shared_secret", "authentication_secret", "accounting_secret"):
                secret = str(server.get(field) or "")
                if secret and (field, secret) not in seen:
                    seen.add((field, secret))
                    items.append((name, secret))
        return items

    async def on_disconnect(session_id: str, username: str, peer: str,
                            server_name: str) -> None:
        """收到校验通过的 Disconnect-Request：把匹配到的在线会话判定为掉线。"""
        session = runtime.get_session()
        if session is None:
            logger.warning("radius", "收到 Disconnect-Request，但当前没有运行中的测试会话", {
                "peer": peer,
                "username": username or "-",
                "session_id": session_id or "-",
            })
            return
        target = await session.mark_forced_offline(session_id, username)
        if target is None:
            logger.warning("radius", "Disconnect-Request 未匹配到在线会话", {
                "peer": peer,
                "username": username or "-",
                "session_id": session_id or "-",
                "hint": "请核对服务端下发的 Acct-Session-Id 或 User-Name 与本工具记录是否一致",
            })
        else:
            logger.info("radius", "强制下线已计入统计", {
                "username": target.username,
                "session_id": target.session_id,
                "server": server_name or "-",
            })

    listener.set_secret_provider(secret_candidates)
    listener.set_handler(on_disconnect)
    runtime.set_disconnect_listener(listener)
    await listener.start()


def _install_loop_exception_handler() -> None:
    """
    抑制 Windows Proactor 传输层在浏览器断开 WebSocket 时抛出的
    ConnectionResetError / BrokenPipeError 噪声（无害，但会刷屏）。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if loop.get_exception_handler() is not None:
        return
    default_handler = loop.default_exception_handler

    def handler(loop, context):
        exc = context.get("exception")
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        if default_handler:
            default_handler(context)

    loop.set_exception_handler(handler)
