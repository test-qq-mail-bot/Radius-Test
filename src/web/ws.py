# -*- coding: utf-8 -*-
"""
WebSocket 管理模块。

职责：
    1. 管理前端 WebSocket 连接；
    2. 向全部连接推送实时测试数据；
    3. 实现 2 秒心跳与「连续 3 次失败自动终止测试」保护；
    4. 实现「前端全部断开超过宽限期自动终止测试」保护。

保护原则（项目书 16.1）：
    宁可提前停止测试，也不能在用户已经无法控制页面时继续产生大量 RADIUS 请求。

实现：
    后端每 2 秒向前端发送一次 ping，
    前端收到后立即回复 pong，
    后端连续 3 次（约 6 秒）未收到 pong 即终止当前测试（HEARTBEAT_TIMEOUT）。

    页面关闭或刷新时 WebSocket 会断开，此时连接从集合中移除，
    心跳监控将无人可监，因此额外增加「全部连接断开」判定：
    曾经连上过、且连续 DISCONNECT_GRACE 秒没有任何连接时，
    判定浏览器已断开并终止测试（BROWSER_DISCONNECTED）。
    宽限期用于兼容页面刷新场景（断开后通常在 1 秒内重新连上）。

    仅通过接口启动测试、从未打开页面的场景不会触发该保护。
"""

import asyncio
import json
import time
from typing import Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

from ..logging import logger

# 心跳间隔（秒）
HEARTBEAT_INTERVAL = 2.0
# 连续失败次数上限
HEARTBEAT_MAX_FAIL = 3
# 全部连接断开后的宽限时间（秒），超时判定浏览器已断开。
# 必须小于会话自身的心跳超时（HEARTBEAT_INTERVAL * HEARTBEAT_MAX_FAIL = 6 秒），
# 否则页面关闭场景会先被会话心跳超时判定为 HEARTBEAT_TIMEOUT，
# 导致 BROWSER_DISCONNECTED 原因永远不会出现。
# 取 3 秒：页面刷新时新页面通常在 1 秒内重新连上，不会被误判。
DISCONNECT_GRACE = 3.0


class WebSocketManager:
    """
    WebSocket 连接管理器。

    参数：
        session_provider: 无参回调，返回当前测试会话对象或 None
    """

    def __init__(self, session_provider=None):
        self._connections: Set[WebSocket] = set()
        self._session_provider = session_provider
        self._monitor_task: Optional[asyncio.Task] = None
        self._last_seen: dict = {}
        self._fail_count: dict = {}
        self._last_beat_sent = 0.0
        self._lock = asyncio.Lock()
        # 是否曾经有页面连接（用于区分接口启动测试与页面启动测试）
        self._had_connection = False
        # 全部连接断开的起始时刻，None 表示当前有连接
        self._no_connection_since: Optional[float] = None

    @property
    def connection_count(self) -> int:
        """当前连接数量。"""
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        """接受并登记连接。"""
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
            self._last_seen[id(websocket)] = time.monotonic()
            self._fail_count[id(websocket)] = 0
            self._had_connection = True
            self._no_connection_since = None
        logger.debug("websocket", "前端已连接", {"total": self.connection_count})
        await self._send(websocket, {
            "type": "connected",
            "data": {"heartbeat_interval": HEARTBEAT_INTERVAL},
        })

    async def disconnect(self, websocket: WebSocket) -> None:
        """移除连接。"""
        async with self._lock:
            self._connections.discard(websocket)
            self._last_seen.pop(id(websocket), None)
            self._fail_count.pop(id(websocket), None)
            if not self._connections and self._had_connection:
                if self._no_connection_since is None:
                    self._no_connection_since = time.monotonic()
            else:
                self._no_connection_since = None
        logger.debug("websocket", "前端已断开", {"total": self.connection_count})

    async def broadcast(self, payload: dict) -> None:
        """向全部连接推送消息。"""
        if not self._connections:
            return
        message = json.dumps(payload, ensure_ascii=False, default=str)
        dead = []
        for websocket in list(self._connections):
            try:
                await websocket.send_text(message)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            await self.disconnect(websocket)

    async def _send(self, websocket: WebSocket, payload: dict) -> None:
        """向单个连接发送消息。"""
        try:
            await websocket.send_text(json.dumps(payload, ensure_ascii=False, default=str))
        except Exception:
            await self.disconnect(websocket)

    # ---------------- 心跳 ----------------

    async def handle_message(self, websocket: WebSocket, text: str) -> None:
        """
        处理前端消息。

        支持：
            {"type":"pong"}     心跳应答
            {"type":"heartbeat"} 前端主动心跳
            {"type":"ping"}     前端探测
        """
        key = id(websocket)
        try:
            payload = json.loads(text)
        except ValueError:
            return
        message_type = payload.get("type") if isinstance(payload, dict) else ""
        if message_type in ("pong", "heartbeat"):
            self._last_seen[key] = time.monotonic()
            self._fail_count[key] = 0
            session = self._session_provider() if self._session_provider else None
            if session is not None:
                session.heartbeat()
        elif message_type == "ping":
            await self._send(websocket, {"type": "pong", "data": {}})

    async def start_monitor(self) -> None:
        """启动心跳监控任务。"""
        if self._monitor_task is not None and not self._monitor_task.done():
            return
        self._monitor_task = asyncio.create_task(self._monitor())

    async def stop_monitor(self) -> None:
        """停止心跳监控任务。"""
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except (asyncio.CancelledError, Exception):
                pass
            self._monitor_task = None

    async def _monitor(self) -> None:
        """
        心跳监控循环。

        每 HEARTBEAT_INTERVAL 秒向全部连接发送 ping，
        并检查是否有连接连续多次未应答。
        """
        from ..testing import state as state_mod

        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                now = time.monotonic()
                await self.broadcast({
                    "type": "ping",
                    "data": {"timestamp": now},
                })
                expired = []
                for key, last in list(self._last_seen.items()):
                    if now - last > HEARTBEAT_INTERVAL * (HEARTBEAT_MAX_FAIL - 1):
                        self._fail_count[key] = self._fail_count.get(key, 0) + 1
                    else:
                        self._fail_count[key] = 0
                    if self._fail_count.get(key, 0) >= HEARTBEAT_MAX_FAIL:
                        expired.append(key)
                if expired:
                    logger.warning("websocket", "心跳连续失败，判定前端失联", {
                        "count": len(expired),
                    })
                    session = self._session_provider() if self._session_provider else None
                    if session is not None and session.running:
                        await session.stop(state_mod.HEARTBEAT_TIMEOUT)
                    for key in expired:
                        self._last_seen.pop(key, None)
                        self._fail_count.pop(key, None)
                await self._check_all_disconnected(now, state_mod)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("websocket", "心跳监控异常", {"error": str(exc)}, exc_info=True)
                await asyncio.sleep(1.0)

    async def _check_all_disconnected(self, now: float, state_mod) -> None:
        """
        检查「全部页面已断开」并按需终止测试。

        触发条件（三者同时满足）：
            1. 曾经有页面连接过（排除纯接口启动测试的场景）；
            2. 当前没有任何连接；
            3. 无连接状态已持续超过 DISCONNECT_GRACE 秒（兼容页面刷新）。

        说明：
            触发后重置 _had_connection，避免测试停止后重复触发，
            直到下一个页面重新连接才会再次启用该保护。
        """
        if not self._had_connection or self._connections:
            return
        if self._no_connection_since is None:
            self._no_connection_since = now
            return
        if now - self._no_connection_since < DISCONNECT_GRACE:
            return
        session = self._session_provider() if self._session_provider else None
        self._had_connection = False
        self._no_connection_since = None
        if session is None or not getattr(session, "running", False):
            return
        logger.warning("websocket", "前端全部断开且超过宽限期，终止测试", {
            "grace": DISCONNECT_GRACE,
        })
        await session.stop(state_mod.BROWSER_DISCONNECTED)

    async def close_all(self) -> None:
        """关闭全部连接。"""
        for websocket in list(self._connections):
            try:
                await websocket.close()
            except Exception:
                pass
        self._connections.clear()
        self._last_seen.clear()
        self._fail_count.clear()
