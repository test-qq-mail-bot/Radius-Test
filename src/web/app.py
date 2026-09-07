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
        """应用启动：开启心跳监控。"""
        await manager.start_monitor()
        _install_loop_exception_handler()
        logger.info("web", "Web 应用已启动", {
            "software": "%s %s" % (version.SOFTWARE_NAME, version.SOFTWARE_VERSION),
        })
        logger.debug("web", "调试日志已启用，WebSocket 断连噪声已抑制", {})


    @app.on_event("shutdown")
    async def on_shutdown():
        """应用停止：停止心跳监控并关闭连接。"""
        session = runtime.get_session()
        if session is not None and session.running:
            from ..testing import state as state_mod

            await session.stop(state_mod.SYSTEM_ERROR)
        await manager.stop_monitor()
        await manager.close_all()

    return app


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
