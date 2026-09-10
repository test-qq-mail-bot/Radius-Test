# -*- coding: utf-8 -*-
"""
计费与在线会话模块。

职责：
    1. 维护测试过程中的在线会话状态；
    2. 周期性发送 Accounting Interim-Update；
    3. 按「间隔 × 连续失败次数」判定掉线；
    4. 测试结束时统一发送 Accounting-Stop。

在线判定（用户确认口径）：
    Access-Accept 且 Accounting-Start 成功 = 在线

掉线判定（用户确认口径）：
    每 interim_interval 秒发送一次 Interim-Update，
    连续 interim_max_fail 次未收到 Accounting-Response 即判定掉线。
    默认值：60 秒 × 3 次 = 180 秒。
"""

import asyncio
import time
from typing import Dict, Optional

from ..logging import logger


class OnlineSession:
    """
    单个在线会话。

    属性：
        username: 用户名
        server_name: RADIUS Server 名称
        session_id: 计费会话 ID
        start_time: 上线时间戳（秒）
        interim_fail_count: 连续 Interim-Update 失败次数
        last_interim_time: 上次发送 Interim-Update 的时间戳
        offline: 是否已掉线
    """

    __slots__ = ("username", "server_name", "session_id", "start_time",
                 "interim_fail_count", "last_interim_time", "offline",
                 "protocol", "task_id", "interim_disabled")

    def __init__(self, username: str, server_name: str, session_id: str,
                 protocol: str = "", task_id: str = "",
                 interim_disabled: bool = False):
        self.username = username
        self.server_name = server_name
        self.session_id = session_id
        self.protocol = protocol
        self.task_id = task_id
        # True 表示该会话不参与 Interim-Update 掉线判定
        # （用于「认证成功即在线」口径下计费未上线的会话）
        self.interim_disabled = interim_disabled
        self.start_time = time.time()
        self.interim_fail_count = 0
        self.last_interim_time = self.start_time
        self.offline = False


class OnlineSessionManager:
    """
    在线会话管理器。

    参数：
        client: RadiusClient 实例
        interim_interval: Interim-Update 间隔（秒），0 表示不发送
        interim_max_fail: 连续失败次数上限，达到即判定掉线
    """

    def __init__(self, client, interim_interval: int = 60, interim_max_fail: int = 3):
        self._client = client
        self._interval = max(0, int(interim_interval))
        self._max_fail = max(1, int(interim_max_fail))
        self._sessions: Dict[str, OnlineSession] = {}
        self._lock = asyncio.Lock()
        self._runner_task: Optional[asyncio.Task] = None
        self._stopped = False
        # 发送 Accounting-Stop 时的最大并发数
        self.STOP_CONCURRENCY = 200

    @property
    def online_count(self) -> int:
        """当前在线会话数量。"""
        return sum(1 for s in self._sessions.values() if not s.offline)

    @property
    def tracked_count(self) -> int:
        """被跟踪的会话总数（含已掉线但尚未清理的）。"""
        return len(self._sessions)

    def online_usernames(self) -> set:
        """返回当前在线（未掉线）的用户名集合，供派发时避免重复登录。"""
        return {s.username for s in self._sessions.values() if not s.offline}

    def configure(self, interim_interval: int, interim_max_fail: int) -> None:
        """更新 Interim-Update 参数。"""
        self._interval = max(0, int(interim_interval))
        self._max_fail = max(1, int(interim_max_fail))

    async def add(self, session: OnlineSession) -> None:
        """登记一个在线会话。"""
        async with self._lock:
            self._sessions[session.session_id] = session

    async def remove(self, session_id: str) -> None:
        """移除一个会话。"""
        async with self._lock:
            self._sessions.pop(session_id, None)

    def get(self, session_id: str) -> Optional[OnlineSession]:
        """查询会话。"""
        return self._sessions.get(session_id)

    async def start(self) -> None:
        """启动后台 Interim-Update 任务。"""
        if self._interval <= 0:
            return
        if self._runner_task is not None and not self._runner_task.done():
            return
        self._stopped = False
        self._runner_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """停止后台任务。"""
        self._stopped = True
        if self._runner_task is not None:
            self._runner_task.cancel()
            try:
                await self._runner_task
            except (asyncio.CancelledError, Exception):
                pass
            self._runner_task = None

    async def _run(self) -> None:
        """
        后台循环。

        每隔 interval 秒对全部在线会话发送一次 Interim-Update，
        失败计数达到上限时标记掉线。
        """
        while not self._stopped:
            await asyncio.sleep(max(1, self._interval))
            if self._stopped:
                break
            servers = {}
            snapshot = list(self._sessions.values())
            for session in snapshot:
                if session.offline or session.interim_disabled or self._stopped:
                    continue
                try:
                    server = servers.get(session.server_name)
                    if server is None:
                        server = await self._resolve_server(session.server_name)
                        servers[session.server_name] = server
                    if server is None:
                        continue
                    result = await self._client.send_accounting(
                        server,
                        session.username,
                        3,  # Interim-Update
                        session_id=session.session_id,
                        session_time=int(time.time() - session.start_time),
                    )
                    if result.success:
                        session.interim_fail_count = 0
                    else:
                        session.interim_fail_count += 1
                except Exception:
                    session.interim_fail_count += 1
                session.last_interim_time = time.time()
                if session.interim_fail_count >= self._max_fail:
                    session.offline = True

    async def _resolve_server(self, server_name: str):
        """按名称查找 Server 配置。"""
        from ..config import loader

        for server in loader.get_servers():
            if server.get("name") == server_name:
                return server
        return None

    async def stop_all(self) -> int:
        """
        对所有仍在线的会话发送 Accounting-Stop。

        返回：
            成功发送 Stop 的会话数量。

        说明：
            在线用户可能达到上万，串行发送会导致停止过程极慢，
            因此采用受限并发（STOP_CONCURRENCY）批量发送。
        """
        sessions = list(self._sessions.values())
        if not sessions:
            return 0
        servers = {}

        async def resolve(session: OnlineSession):
            """按名称解析 Server 配置，带缓存避免重复查询。"""
            if session.server_name not in servers:
                servers[session.server_name] = await self._resolve_server(session.server_name)
            return servers[session.server_name]

        # 失败原因归类计数器：在线用户可能上万，逐个打印日志会淹没日志，
        # 因此只在最后汇总输出，既保留可观测性又不产生日志风暴。
        failure_reasons: Dict[str, int] = {}

        def record_failure(reason: str) -> None:
            """归类记录一次失败原因，仅保留前若干种以免字典无界增长。"""
            key = str(reason)[:120] or "未知原因"
            if key not in failure_reasons and len(failure_reasons) >= 10:
                key = "其他"
            failure_reasons[key] = failure_reasons.get(key, 0) + 1

        async def stop_one(session: OnlineSession) -> bool:
            """对单个会话发送 Accounting-Stop。"""
            try:
                server = await resolve(session)
                if server is None:
                    record_failure("Server 配置不存在：%s" % session.server_name)
                    return False
                result = await self._client.send_accounting(
                    server,
                    session.username,
                    2,  # Stop
                    session_id=session.session_id,
                    session_time=int(time.time() - session.start_time),
                )
                if not result.success:
                    record_failure(getattr(result, "error", "") or "服务器未返回成功响应")
                return bool(result.success)
            except Exception as exc:
                record_failure("%s: %s" % (type(exc).__name__, exc))
                return False
            finally:
                await self.remove(session.session_id)

        semaphore = asyncio.Semaphore(self.STOP_CONCURRENCY)

        async def guarded(session: OnlineSession) -> bool:
            async with semaphore:
                return await stop_one(session)

        results = await asyncio.gather(
            *[guarded(session) for session in sessions], return_exceptions=True)
        count = 0
        for item in results:
            if item is True:
                count += 1
            elif isinstance(item, BaseException):
                # gather 使用 return_exceptions=True，异常会作为结果返回，
                # 需要在此归类，避免异常被静默丢弃。
                record_failure("%s: %s" % (type(item).__name__, item))
        logger.info("accounting", "Accounting-Stop 批量发送完成", {
            "total": len(sessions),
            "success": count,
            "failed": len(sessions) - count,
        })
        if failure_reasons:
            # 失败明细按出现次数降序，最多输出 5 类
            top = sorted(failure_reasons.items(), key=lambda kv: kv[1], reverse=True)[:5]
            logger.warning("accounting", "Accounting-Stop 存在发送失败", {
                "种类数": len(failure_reasons),
                "明细": "；".join("%s × %d" % (reason, num) for reason, num in top),
            })
        return count

    async def clear(self) -> None:
        """清空全部会话记录，不发送 Stop。"""
        async with self._lock:
            self._sessions.clear()
