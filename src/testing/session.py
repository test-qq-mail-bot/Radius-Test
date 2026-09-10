# -*- coding: utf-8 -*-
"""
测试会话管理模块。

职责：
    1. 管理一次性能测试任务的完整生命周期；
    2. 组合速率限制、并发控制、任务队列与停止机制；
    3. 实时统计测试结果指标（项目书第 27 节）；
    4. 通过回调向 WebSocket 推送实时数据。

统计指标（项目书 27）：
    总请求数、成功数、失败数、超时数、取消数、当前在线数、
    成功率、失败率、最大响应时间、最小响应时间。
    不使用 P95 / P99。
"""

import asyncio
import time
from typing import Callable, List, Optional

from ..accounting import acct as acct_mod
from ..common import time_util
from ..common import uuid_util
from ..config import loader
from ..database import dao
from ..logging import logger
from ..performance.limiter import RateLimiter
from ..performance.pool import ConcurrencyController
from ..radius.client import RadiusClient
from . import state as state_mod
from . import task as task_mod

# 心跳超时：2 秒 × 3 次 ≈ 6 秒（项目书 16.1）
HEARTBEAT_INTERVAL = 2.0
HEARTBEAT_MAX_FAIL = 3


class TestSession:
    """
    一次性能测试任务。

    参数：
        options: 测试参数字典
        broadcast: 实时数据推送回调，签名为 async def broadcast(payload: dict)
        socket_manager: UDP Socket 池管理器
    """

    def __init__(self, options: dict, broadcast: Optional[Callable] = None,
                 socket_manager=None):
        self.task_id = uuid_util.new_task_id()
        self.options = dict(options or {})
        self._broadcast = broadcast
        self._socket_manager = socket_manager
        self._client = RadiusClient(socket_manager) if socket_manager else None
        self._limiter = RateLimiter(float(self.options.get("rate") or 10))
        self._controller = ConcurrencyController(
            int(self.options.get("concurrency") or 10000))
        self._online = acct_mod.OnlineSessionManager(
            self._client,
            int(self.options.get("interim_interval") or 60),
            int(self.options.get("interim_max_fail") or 3),
        )
        self.status = state_mod.PENDING
        self.stop_reason = ""
        self.started_at = 0.0
        self.finished_at = 0.0
        self._tasks: List[asyncio.Task] = []
        # 在途登录任务：用户名 -> 在途数量，避免同一用户在任务未完成时被重复派发
        self._pending: dict = {}
        self._task_user: dict = {}
        self._runner: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._heartbeat_ok = time.monotonic()
        self._last_beat = 0.0
        self._lock = asyncio.Lock()
        # 统计指标
        self.total = 0
        self.success_count = 0
        self.failed_count = 0
        self.timeout_count = 0
        self.cancelled_count = 0
        self.min_response_time = 0.0
        self.max_response_time = 0.0
        self.offline_count = 0

    # ---------------- 属性 ----------------

    @property
    def server_name(self) -> str:
        """目标 RADIUS Server 名称。"""
        return str(self.options.get("server_name") or "")

    @property
    def protocol(self) -> str:
        """认证协议。"""
        return str(self.options.get("protocol") or "pap")

    @property
    def running(self) -> bool:
        """是否正在运行。"""
        return self.status == state_mod.RUNNING

    @property
    def online_count(self) -> int:
        """当前在线用户数。"""
        return self._online.online_count

    @property
    def elapsed_seconds(self) -> float:
        """已运行秒数。"""
        if not self.started_at:
            return 0.0
        end = self.finished_at or time.time()
        return round(end - self.started_at, 3)

    # ---------------- 生命周期 ----------------

    async def start(self) -> None:
        """启动测试。"""
        if self.status == state_mod.RUNNING:
            return
        self.status = state_mod.RUNNING
        self.started_at = time.time()
        self._heartbeat_ok = time.monotonic()
        self._stop_event.clear()
        dao.save_session({
            "task_id": self.task_id,
            "start_time": time_util.format_log_time(),
            "end_time": "",
            "server": self.server_name,
            "protocol": self.protocol,
            "status": state_mod.SESSION_RUNNING,
            "stop_reason": "",
            "concurrency": self._controller.max_concurrency,
            "rate": int(self._limiter.rate),
        })
        await self._online.start()
        self._runner = asyncio.create_task(self._run())
        logger.info("testing", "测试任务已启动", {
            "task_id": self.task_id,
            "server": self.server_name,
            "protocol": self.protocol,
            "rate": self._limiter.rate,
            "concurrency": self._controller.max_concurrency,
            "users": len(self.options.get("users") or []),
        })
        await self._push()

    async def stop(self, reason: str = state_mod.USER_STOP) -> None:
        """
        停止测试。

        参数：
            reason: 停止原因，必须是 STOP_REASONS 之一
        """
        if reason not in state_mod.STOP_REASONS:
            reason = state_mod.SYSTEM_ERROR
        if self.status not in (state_mod.RUNNING, state_mod.PENDING):
            return
        self.status = state_mod.ABORTED
        self.stop_reason = reason
        self._stop_event.set()
        logger.info("testing", "测试任务停止中", {
            "task_id": self.task_id,
            "reason": state_mod.stop_reason_text(reason),
        })
        # 收尾顺序固定为：取消在途任务 -> 停止计费心跳 -> 发送 Accounting-Stop -> 落库。
        # 使用 try/finally 保证即使中途抛出异常也一定会写入会话记录，
        # 避免出现「任务已结束但会话未落库」或「先落库、后发 Accounting-Stop」的顺序颠倒。
        try:
            # 取消尚未完成的用户任务
            for user_task in self._tasks:
                if not user_task.done():
                    user_task.cancel()
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)
                self.cancelled_count += sum(
                    1 for t in self._tasks if t.cancelled()
                )
            await self._online.stop()
            # 对仍在线的用户发送 Accounting-Stop
            stopped = await self._online.stop_all()
            logger.info("testing", "已发送 Accounting-Stop", {"count": stopped})
            # 若 stop() 由 _run 内部触发，_runner 即当前任务，不能自我取消
            if (self._runner is not None and not self._runner.done()
                    and self._runner is not asyncio.current_task()):
                self._runner.cancel()
        finally:
            await self._finalize()

    def heartbeat(self) -> None:
        """收到前端心跳，刷新存活时间。"""
        self._heartbeat_ok = time.monotonic()

    def heartbeat_expired(self) -> bool:
        """判断心跳是否已超时（约 6 秒）。"""
        if not self.running:
            return False
        return (time.monotonic() - self._heartbeat_ok) > (
            HEARTBEAT_INTERVAL * HEARTBEAT_MAX_FAIL
        )

    # ---------------- 内部实现 ----------------

    async def _run(self) -> None:
        """主循环：按速率与并发上限持续派发用户任务。"""
        users = list(self.options.get("users") or [])
        if not users:
            await self.stop(state_mod.CONFIG_ERROR)
            return
        server = self._find_server()
        if server is None:
            await self.stop(state_mod.CONFIG_ERROR)
            return
        save_packets = bool(self.options.get("save_packets"))
        enable_accounting = bool(self.options.get("enable_accounting", True))
        online_criteria = str(self.options.get("online_criteria") or "accounting")
        peer_challenge_bytes = int(self.options.get("peer_challenge_bytes") or 8)
        index = 0
        push_deadline = time.monotonic()
        try:
            while not self._stop_event.is_set():
                if self.heartbeat_expired():
                    await self.stop(state_mod.HEARTBEAT_TIMEOUT)
                    return
                # 已在线的用户不再重复登录：在线数上限即用户数，掉线后可重新登录
                online_names = self._online.online_usernames()
                picked = None
                for _ in range(len(users)):
                    candidate = users[index % len(users)]
                    index += 1
                    # 已在线、或已有在途登录任务的用户不再派发
                    if (candidate[0] not in online_names
                            and self._pending.get(candidate[0], 0) == 0):
                        picked = candidate
                        break
                if picked is None:
                    # 全部用户均在线：空闲等待，不消耗速率令牌
                    if time.monotonic() >= push_deadline:
                        push_deadline = time.monotonic() + 0.5
                        await self._push()
                    await asyncio.sleep(0.2)
                    continue
                username, password = picked
                await self._limiter.acquire()
                if self._stop_event.is_set():
                    break
                if not self._controller.try_acquire():
                    # 任务数量达到上限，按保护策略停止新增
                    await self.stop(state_mod.RESOURCE_LIMIT)
                    return
                user_task = asyncio.create_task(
                    self._execute(server, username, password, save_packets,
                                  enable_accounting, peer_challenge_bytes,
                                  online_criteria)
                )
                self._tasks.append(user_task)
                self._pending[username] = self._pending.get(username, 0) + 1
                self._task_user[user_task] = username
                user_task.add_done_callback(self._on_task_done)
                # 清理已结束的任务，避免列表无限增长
                if len(self._tasks) > 20000:
                    self._tasks = [t for t in self._tasks if not t.done()]
                if time.monotonic() >= push_deadline:
                    push_deadline = time.monotonic() + 0.5
                    await self._push()
            # 循环退出只可能由 _stop_event 触发，而该事件仅由 stop() 设置，
            # 因此收尾统一交由 stop() 负责，此处不再重复调用 _finalize()，
            # 避免与 stop() 竞争造成「先落库、后发 Accounting-Stop」的顺序颠倒。
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("testing", "测试主循环异常", {"error": str(exc)}, exc_info=True)
            await self.stop(state_mod.SYSTEM_ERROR)

    async def _execute(self, server: dict, username: str, password: str,
                       save_packets: bool, enable_accounting: bool,
                       peer_challenge_bytes: int,
                       online_criteria: str = "accounting"):
        """
        执行单个用户任务，释放并发额度。

        返回：
            TaskOutcome 对象，供统计回调累计指标。
        """
        try:
            return await task_mod.run_user_task(
                self._client, server, username, password, self.protocol,
                self.task_id, save_packets, self._online,
                enable_accounting, peer_challenge_bytes, online_criteria,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("testing", "用户任务执行异常", {
                "username": username, "error": str(exc),
            }, exc_info=True)
            return None
        finally:
            self._controller.release()

    def _on_task_done(self, user_task: asyncio.Task) -> None:
        """用户任务结束回调，累计统计。"""
        # 先释放在途标记，避免同一用户被重复派发
        username = self._task_user.pop(user_task, None)
        if username:
            remaining = self._pending.get(username, 0) - 1
            if remaining > 0:
                self._pending[username] = remaining
            else:
                self._pending.pop(username, None)
        self.total += 1
        if user_task.cancelled():
            self.cancelled_count += 1
            return
        outcome = None
        try:
            outcome = user_task.result()
        except Exception:
            self.failed_count += 1
            return
        if outcome is None:
            return
        if outcome.status == state_mod.SUCCESS:
            self.success_count += 1
        elif outcome.status == state_mod.TIMEOUT:
            self.timeout_count += 1
            self.failed_count += 1
        elif outcome.status == state_mod.FAILED:
            self.failed_count += 1
        elif outcome.status == state_mod.CANCELLED:
            self.cancelled_count += 1
        if outcome.response_time > 0:
            if self.min_response_time == 0 or outcome.response_time < self.min_response_time:
                self.min_response_time = outcome.response_time
            if outcome.response_time > self.max_response_time:
                self.max_response_time = outcome.response_time

    def _find_server(self) -> Optional[dict]:
        """按名称查找目标 Server 配置。"""
        for server in loader.get_servers():
            if server.get("name") == self.server_name:
                return server
        return None

    async def _finalize(self) -> None:
        """结束测试并写入会话记录。"""
        if self.finished_at:
            return
        self.finished_at = time.time()
        self.status = state_mod.ABORTED if self.stop_reason else state_mod.SUCCESS
        dao.save_session({
            "task_id": self.task_id,
            "start_time": time_util.format_display(
                time_util.now()) if not self.started_at else "",
            "end_time": time_util.format_log_time(),
            "server": self.server_name,
            "protocol": self.protocol,
            "status": state_mod.SESSION_STOPPED if self.stop_reason
            else state_mod.SESSION_COMPLETED,
            "stop_reason": self.stop_reason,
            "concurrency": self._controller.max_concurrency,
            "rate": int(self._limiter.rate),
        })
        logger.info("testing", "测试任务已结束", {
            "task_id": self.task_id,
            "total": self.total,
            "success": self.success_count,
            "failed": self.failed_count,
            "timeout": self.timeout_count,
            "reason": state_mod.stop_reason_text(self.stop_reason) or "自然结束",
        })
        await self._push()

    async def _push(self) -> None:
        """推送实时数据。"""
        if self._broadcast is None:
            return
        try:
            await self._broadcast(self.snapshot())
        except Exception as exc:
            logger.warning("testing", "实时数据推送失败", {"error": str(exc)})

    # ---------------- 对外数据 ----------------

    def snapshot(self) -> dict:
        """返回测试会话实时快照。"""
        success_rate = (self.success_count / self.total * 100) if self.total else 0.0
        failed_rate = (self.failed_count / self.total * 100) if self.total else 0.0
        return {
            "task_id": self.task_id,
            "status": self.status,
            "status_text": state_mod.state_text(self.status),
            "stop_reason": self.stop_reason,
            "stop_reason_text": state_mod.stop_reason_text(self.stop_reason),
            "server": self.server_name,
            "protocol": self.protocol,
            "elapsed_seconds": self.elapsed_seconds,
            "total": self.total,
            "success": self.success_count,
            "failed": self.failed_count,
            "timeout": self.timeout_count,
            "cancelled": self.cancelled_count,
            "online": self.online_count,
            "success_rate": round(success_rate, 2),
            "failed_rate": round(failed_rate, 2),
            "max_response_time": round(self.max_response_time, 3),
            "min_response_time": round(self.min_response_time, 3),
            "concurrency": self._controller.snapshot(),
            "rate": self._limiter.snapshot(),
        }
