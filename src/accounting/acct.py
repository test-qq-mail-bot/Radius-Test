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
# 会话实体已拆到兄弟模块（单文件 ≤20KB 约束）：本模块只保留管理器。
# 顶部导入即再导出，`acct_mod.OnlineSession` 的既有导入路径保持可用。
from .model import OnlineSession


class OnlineSessionManager:
    """
    在线会话管理器。

    参数：
        client: RadiusClient 实例
        interim_interval: Interim-Update 间隔（秒），0 表示不发送
        interim_max_fail: 连续失败次数上限，达到即判定掉线
    """

    def __init__(self, client, interim_interval: int = 60, interim_max_fail: int = 3,
                 accounting_timeout: float = 0.0, accounting_retry_count: int = 0,
                 save_packets: bool = False):
        self._client = client
        self._interval = max(0, int(interim_interval))
        self._max_fail = max(1, int(interim_max_fail))
        # Interim-Update 的计费超时与重试：使用「短超时」而非 Server 默认。
        # 否则服务端宕机时单次 Interim 会阻塞 timeout×retry（默认 5s×3=15s），
        # 掉线判定在常规测试窗口内几乎无法触发（需求3 实机暴露的缺陷）。
        self._acct_timeout = float(accounting_timeout or 0.0)
        self._acct_retry = int(accounting_retry_count or 0)
        # 是否落库计费报文（Start/Interim/Stop），用于详情页聚合展示（需求4）
        self._save_packets = bool(save_packets)
        self._sessions: Dict[str, OnlineSession] = {}
        self._lock = asyncio.Lock()
        self._runner_task: Optional[asyncio.Task] = None
        self._stopped = False
        # 发送 Accounting-Stop 时的最大并发数
        self.STOP_CONCURRENCY = 200
        # 掉线计量（需求3）：累计掉线次数与累计掉线时长
        self._drop_count = 0
        self._total_drop_duration = 0.0

    @property
    def online_count(self) -> int:
        """当前在线会话数量。"""
        return sum(1 for s in self._sessions.values() if not s.offline)

    @property
    def tracked_count(self) -> int:
        """被跟踪的会话总数（含已掉线但尚未清理的）。"""
        return len(self._sessions)

    @property
    def drop_count(self) -> int:
        """累计掉线次数（每次从在线到离线的跃迁计 1 次）。"""
        return self._drop_count

    @property
    def total_drop_duration(self) -> float:
        """
        累计「掉线前的在线时长」（秒，需求2 口径）。

        每次判定掉线（Interim 连续失败或服务端强制下线）时，把该会话
        start_time -> offline_start_time 的在线时长累加进来；
        恢复后不再累加离线时长。因此该值表示用户掉线前「平均保持了多久在线」，
        已恢复或仍离线的会话都不额外计入。
        """
        return self._total_drop_duration

    @property
    def dropped_user_count(self) -> int:
        """曾发生掉线的去重用户数。"""
        return sum(1 for s in self._sessions.values() if s.has_dropped)

    @property
    def current_offline_count(self) -> int:
        """当前仍离线的会话数。"""
        return sum(1 for s in self._sessions.values() if s.offline)

    def online_usernames(self) -> set:
        """返回当前在线（未掉线）的用户名集合，供派发时避免重复登录。"""
        return {s.username for s in self._sessions.values() if not s.offline}

    def configure(self, interim_interval: int, interim_max_fail: int) -> None:
        """更新 Interim-Update 参数。"""
        self._interval = max(0, int(interim_interval))
        self._max_fail = max(1, int(interim_max_fail))

    def set_save_packets(self, flag: bool) -> None:
        """
        动态更新「是否落库计费报文」。

        单用户测试管理器是进程级单例，创建后长期驻留；配置（保存报文）
        可在运行期变更，因此每次发起测试前都需按最新配置刷新该开关，
        否则会出现「Start 报文落库、Stop 报文不落库」的不一致（实测缺陷）。
        """
        self._save_packets = bool(flag)

    async def mark_forced_offline(self, session_id: str = "",
                                  username: str = "") -> Optional[OnlineSession]:
        """
        处理服务端主动下发的 Disconnect-Request：把匹配到的会话立即判定为掉线。

        匹配顺序：先按计费会话 ID（Acct-Session-Id），再按用户名。
        返回匹配到的会话；未匹配到时返回 None（说明服务端给出的标识与本工具记录不一致，
        调用方应把服务端下发的属性打进日志，便于比对）。

        说明：
            服务端已明确要求该用户下线，因此不再等待 Interim-Update 失败次数累积，
            直接把会话置为离线并计入掉线统计。
        """
        async with self._lock:
            target = None
            if session_id:
                target = self._sessions.get(session_id)
            if target is None and username:
                for session in self._sessions.values():
                    if session.username == username and not session.offline:
                        target = session
                        break
            if target is None:
                return None
            if not target.offline:
                target.offline = True
                target.offline_start_time = time.time()
                target.has_dropped = True
                self._drop_count += 1
                # 结算「掉线前在线时长」：start_time -> offline_start_time
                online_duration = target.offline_start_time - target.start_time
                if online_duration < 0:
                    online_duration = 0.0
                self._total_drop_duration += online_duration
                logger.info("accounting", "服务端强制下线：会话已判定掉线", {
                    "username": target.username,
                    "session_id": target.session_id,
                    "server": target.server_name,
                    "online_duration_s": round(online_duration, 3),
                })
            else:
                logger.info("accounting", "服务端强制下线：该会话此前已掉线", {
                    "username": target.username, "session_id": target.session_id})
            # 已明确离线：把失败计数补到阈值，避免后续 Interim 计数被清零后重复判定
            target.interim_fail_count = self._max_fail
            return target

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

    def _save_acct_packet(self, session: "OnlineSession", result,
                           status_type: int) -> None:
        """
        落库一次计费报文（Interim/Stop），失败静默忽略，不阻断主流程（需求4）。

        仅 when self._save_packets 开启；请求报文即使无响应也会保留，便于排查。
        """
        if not self._save_packets or result is None:
            return
        try:
            from ..testing import packets as packets_mod
            packets_mod.save_accounting(session.task_id, session.username,
                                        session.server_name, result, status_type)
        except Exception as exc:
            logger.debug("accounting", "计费报文落库失败（已忽略）",
                         {"username": session.username, "error": str(exc)})

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
                # 已掉线的会话仍需继续发送 Interim，以便检测到恢复（恢复逻辑需要）
                if session.interim_disabled or self._stopped:
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
                        timeout=self._acct_timeout,
                        retry_count=self._acct_retry,
                        dot1x=session.dot1x,
                    )
                    if result.success:
                        # Interim 恢复成功：恢复在线；「掉线前在线时长」已在掉线瞬间计入，
                        # 此处不再累加离线时长（需求2 口径）。
                        self._save_acct_packet(session, result, 3)
                        if session.offline:
                            session.offline = False
                            session.offline_start_time = 0.0
                            session.has_dropped = True
                            logger.info("accounting", "掉线恢复：服务端重新应答计费", {
                                "username": session.username,
                                "session_id": session.session_id,
                                "server": session.server_name,
                            })
                        session.interim_fail_count = 0
                    else:
                        session.interim_fail_count += 1
                        if session.interim_fail_count == 1:
                            # 只在首次失败时记录，避免压测下每个窗口都刷一条
                            logger.debug("accounting", "Interim-Update 首次失败", {
                                "username": session.username,
                                "server": session.server_name,
                                "error": getattr(result, "error", "") or "无响应",
                                "max_fail": self._max_fail,
                            })
                except Exception as exc:
                    session.interim_fail_count += 1
                    logger.debug("accounting", "Interim-Update 异常", {
                        "username": session.username,
                        "error": str(exc),
                        "fail_count": session.interim_fail_count,
                        "max_fail": self._max_fail,
                    })
                session.last_interim_time = time.time()
                # 首次判定掉线：累计次数、记录掉线起始时刻，并结算「掉线前在线时长」
                if session.interim_fail_count >= self._max_fail and not session.offline:
                    session.offline = True
                    session.offline_start_time = time.time()
                    session.has_dropped = True
                    self._drop_count += 1
                    # 结算「掉线前在线时长」：start_time -> offline_start_time
                    online_duration = session.offline_start_time - session.start_time
                    if online_duration < 0:
                        online_duration = 0.0
                    self._total_drop_duration += online_duration
                    logger.info("accounting", "判定掉线：Interim-Update 连续失败达到阈值", {
                        "username": session.username,
                        "session_id": session.session_id,
                        "server": session.server_name,
                        "fail_count": session.interim_fail_count,
                        "max_fail": self._max_fail,
                        "window_s": self._interval * self._max_fail,
                        "online_duration_s": round(online_duration, 3),
                    })

    async def _resolve_server(self, server_name: str):
        """按名称查找 Server 配置。"""
        from ..config import loader

        for server in loader.get_servers():
            if server.get("name") == server_name:
                return server
        return None

    async def stop_session(self, session_id: str) -> bool:
        """
        对指定会话发送 Accounting-Stop 并移除，返回是否命中该会话。

        用于单用户账号认证测试的「重新测试」场景：同一用户再次点击测试时，
        先停掉上一次仍保持的在线会话，避免旧会话无限期发送 Interim-Update。
        """
        session = self.get(session_id)
        if session is None:
            return False
        try:
            server = await self._resolve_server(session.server_name)
            if server is not None:
                result = await self._client.send_accounting(
                    server,
                    session.username,
                    2,  # Stop
                    session_id=session.session_id,
                    session_time=int(time.time() - session.start_time),
                    dot1x=session.dot1x,
                )
                self._save_acct_packet(session, result, 2)
        except Exception as exc:
            logger.debug("accounting", "单会话 Accounting-Stop 失败（已忽略）", {
                "session_id": session_id, "error": str(exc),
            })
        finally:
            await self.remove(session_id)
        return True

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
                    dot1x=session.dot1x,
                )
                self._save_acct_packet(session, result, 2)
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
