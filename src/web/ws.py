# -*- coding: utf-8 -*-
"""
WebSocket 管理模块。

职责：
    1. 管理前端 WebSocket 连接；
    2. 向全部连接推送实时测试数据；
    3. 实现 2 秒 ping/pong 保活，清理失联连接；
    4. 连接断开后的自动重连由前端（ws.js）负责。

范围界定（需求5，重要）：
    本模块**不参与测试存活判定**。测试是否继续，唯一判据是
    「前端是否仍停在测试页面」，由 web.page_liveness 判定：
        - 测试页面每 2 秒上报一次存活；
        - 应用内跳转到非测试页面立即中断测试（PAGE_LEFT）；
        - 测试页面心跳超过 4 秒未上报立即中断（HEARTBEAT_TIMEOUT），
          覆盖关闭标签页 / 关闭浏览器 / 断网等场景。
    因此这里不再因为「WebSocket 连接断开」或「ping/pong 失败」去停止测试——
    那会把「窗口切后台」「刷新页面」等正常操作误判为离开页面。

    连接失联时仅把该连接从集合中移除，等待前端重连。
"""

import asyncio
import json
import time
from typing import Optional, Set

from fastapi import WebSocket

from ..logging import logger

# 连接保活间隔（秒）
HEARTBEAT_INTERVAL = 2.0
# 连续失败次数上限，达到即判定该连接已失联并移除
HEARTBEAT_MAX_FAIL = 3


class WebSocketManager:
    """
    WebSocket 连接管理器。

    参数：
        session_provider: 无参回调，返回当前测试会话对象或 None（保留接口兼容）
    """

    def __init__(self, session_provider=None):
        self._connections: Set[WebSocket] = set()
        self._session_provider = session_provider
        self._monitor_task: Optional[asyncio.Task] = None
        self._last_seen: dict = {}
        self._fail_count: dict = {}
        self._lock = asyncio.Lock()

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

    # ---------------- 心跳（仅用于连接保活） ----------------

    async def handle_message(self, websocket: WebSocket, text: str) -> None:
        """
        处理前端消息。

        支持：
            {"type":"pong"}      心跳应答
            {"type":"heartbeat"} 前端主动心跳
            {"type":"ping"}      前端探测

        说明：此处只维护连接活跃时间，不刷新任何测试存活状态。
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
        连接保活循环。

        每 HEARTBEAT_INTERVAL 秒向全部连接发送 ping，
        连续 HEARTBEAT_MAX_FAIL 次未应答即移除该连接（只清理连接，不停止测试）。
        """
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
                    logger.debug("websocket", "连接心跳无应答，移除连接", {
                        "count": len(expired),
                    })
                    for websocket in list(self._connections):
                        if id(websocket) in expired:
                            await self.disconnect(websocket)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("websocket", "连接保活监控异常", {"error": str(exc)}, exc_info=True)
                await asyncio.sleep(1.0)

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
