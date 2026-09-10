# -*- coding: utf-8 -*-
"""
单用户测试任务模块。

职责：
    执行一次完整的 dot1x 用户登录模拟：
        认证 -> 授权属性提取 -> 结果先落库 -> 计费上线 -> 结果更新 -> 报文保存

结果判定（用户确认口径）：
    成功：Access-Accept 且 Accounting-Start 成功 -> 在线（online_criteria=accounting）
    成功：Access-Accept 即在线，计费失败不阻断（online_criteria=auth）
    失败：认证失败（Access-Reject / 超时 / 协议错误）
    掉线：上线后连续 interim_max_fail 次 Interim-Update 失败

落库时机（关键设计）：
    认证成功即先写入一条结果，计费返回后原地更新（dao.upsert_result）。
    这样即使计费长时间无响应、任务被用户中途停止而取消，
    结果页与详情页也一定有该用户的记录，不会出现「报文有、结果没有」的空档。
"""

import time
from typing import Optional

from ..accounting import acct as acct_mod
from ..authorization import authz
from ..common import time_util
from ..common import uuid_util
from ..database import dao
from ..logging import logger
from ..parser import packet_parser
from . import packets as packets_mod
from . import state as state_mod


class TaskOutcome:
    """单次用户测试的产出。"""

    __slots__ = ("username", "success", "online", "status", "response_time",
                 "error", "authorization", "session_id", "acct_error",
                 "acct_ok", "completed")

    def __init__(self):
        self.username = ""
        self.success = False
        self.online = False
        self.status = state_mod.PENDING
        self.response_time = 0.0
        self.error = ""
        self.authorization = []
        self.session_id = ""
        # 计费失败原因，作为提示信息，不改变认证口径下的成败判定
        self.acct_error = ""
        # 计费是否成功；None 表示未执行计费
        self.acct_ok: Optional[bool] = None
        # 是否已走完正常收尾（用于 finally 判断是否需要兜底落库）
        self.completed = False


# 报文与属性落库由 packets 模块统一提供（与单次测试链路复用）


def _accounting_failure_text(server: dict, acct_result) -> str:
    """生成计费失败原因，超时场景给出可操作的排查提示。"""
    port = server.get("accounting_port") or 1813
    error = getattr(acct_result, "error", "") or ""
    if "超时" in error:
        return ("计费无响应（端口 %s 超时）；请确认服务端已对本 NAS 启用计费，"
                "且计费共享密钥与认证一致" % port)
    return "计费上线失败；%s" % (error or "未收到成功响应")


async def _register_online(online_manager, username: str, server_name: str,
                           session_id: str, protocol: str, task_id: str,
                           interim_disabled: bool) -> None:
    """登记在线会话。"""
    if online_manager is None:
        return
    await online_manager.add(acct_mod.OnlineSession(
        username=username,
        server_name=server_name,
        session_id=session_id,
        protocol=protocol,
        task_id=task_id,
        interim_disabled=interim_disabled,
    ))


async def run_user_task(client, server: dict, username: str, password: str,
                        protocol: str, task_id: str, save_packets: bool,
                        online_manager: "acct_mod.OnlineSessionManager" = None,
                        enable_accounting: bool = True,
                        peer_challenge_bytes: int = 8,
                        online_criteria: str = "accounting",
                        accounting_timeout: float = 0.0,
                        accounting_retry_count: int = 0,
                        accounting_message_authenticator: bool = False) -> TaskOutcome:
    """
    执行一次完整的单用户测试。

    参数：
        client: RadiusClient 实例
        server: RADIUS Server 配置
        username: 用户名
        password: 明文密码
        protocol: 认证协议
        task_id: 所属测试任务 ID
        save_packets: 是否保存 RADIUS 报文
        online_manager: 在线会话管理器，None 表示不做在线跟踪
        enable_accounting: 是否在认证成功后发送计费报文
        peer_challenge_bytes: MS-CHAP 对端挑战值字节数
        online_criteria: 在线判定依据，accounting=计费上线成功才算在线（默认），
            auth=认证成功即在线（计费失败不阻断）
        accounting_timeout: 计费报文单次等待超时（秒），0 表示沿用 Server 配置
        accounting_retry_count: 计费报文重试次数，0 表示沿用 Server 配置
        accounting_message_authenticator: 计费报文是否附加 Message-Authenticator

    返回：
        TaskOutcome 对象。
    """
    outcome = TaskOutcome()
    outcome.username = username
    server_name = str(server.get("name") or server.get("server_address") or "")
    registered = False
    try:
        try:
            result = await client.authenticate(server, username, password, protocol,
                                               peer_challenge_bytes)
        except Exception as exc:
            outcome.status = state_mod.FAILED
            outcome.error = "认证异常；%s" % exc
            logger.error("testing", "认证异常", {"username": username, "error": str(exc)},
                         exc_info=True)
            _persist(task_id, username, server_name, outcome)
            outcome.completed = True
            return outcome

        outcome.response_time = result.response_time_ms

        # 报文解析与保存
        request_packet = result.request_packet
        response_packet = result.response_packet
        if request_packet is not None:
            packet_parser.enrich(request_packet)
        if response_packet is not None:
            packet_parser.enrich(response_packet)

        if save_packets:
            packets_mod.save_packets(task_id, username, server_name,
                                     request_packet, response_packet)

        if not result.success:
            outcome.status = (state_mod.TIMEOUT if "超时" in (result.error or "")
                              else state_mod.FAILED)
            outcome.error = result.error or "认证失败"
            outcome.success = False
            _persist(task_id, username, server_name, outcome)
            outcome.completed = True
            return outcome

        # 认证成功，提取授权属性
        outcome.authorization = authz.extract(response_packet)
        outcome.success = True
        outcome.online = (online_criteria == "auth")
        outcome.status = state_mod.SUCCESS

        # 认证成功即先落一条结果：计费挂起期间被取消也不会丢失该用户记录
        _persist(task_id, username, server_name, outcome)

        if not enable_accounting:
            outcome.completed = True
            return outcome

        # 计费上线
        session_id = uuid_util.new_radius_session_id()
        outcome.session_id = session_id
        if outcome.online:
            # 「认证成功即在线」口径下立刻登记，避免在线数在计费重试期间恒为 0
            await _register_online(online_manager, username, server_name, session_id,
                                   protocol, task_id, interim_disabled=True)
            registered = True

        try:
            acct_result = await client.send_accounting(
                server, username, 1, session_id,
                timeout=accounting_timeout,
                retry_count=accounting_retry_count,
                message_authenticator=accounting_message_authenticator)
        except Exception as exc:
            acct_result = None
            outcome.acct_error = "计费上线异常；%s" % exc
        succeeded = bool(acct_result and acct_result.success)
        outcome.acct_ok = succeeded
        if not succeeded and not outcome.acct_error:
            outcome.acct_error = _accounting_failure_text(server, acct_result)

        if online_criteria == "auth":
            # 认证成功即在线：计费失败不阻断成败，仅记录提示
            outcome.online = True
            outcome.success = True
            outcome.status = state_mod.SUCCESS
            if registered:
                session = online_manager.get(session_id) if online_manager else None
                if session is not None:
                    # 计费上线成功后才参与 Interim-Update 掉线判定
                    session.interim_disabled = not succeeded
            elif online_manager is not None:
                await _register_online(online_manager, username, server_name, session_id,
                                       protocol, task_id, interim_disabled=(not succeeded))
                registered = True
            if not succeeded:
                outcome.error = "提示：计费未成功；%s" % outcome.acct_error
        else:
            outcome.online = succeeded
            outcome.success = succeeded
            outcome.status = state_mod.SUCCESS if succeeded else state_mod.FAILED
            if not succeeded:
                outcome.error = outcome.acct_error
            elif not registered:
                await _register_online(online_manager, username, server_name, session_id,
                                       protocol, task_id, interim_disabled=False)
                registered = True

        _persist(task_id, username, server_name, outcome)
        outcome.completed = True
        return outcome
    finally:
        if not outcome.completed:
            # 任务被取消或中途异常：把已知状态兜底写回，保证结果页始终能看到该用户
            if outcome.status == state_mod.PENDING:
                outcome.status = state_mod.CANCELLED
            if not outcome.error:
                outcome.error = ("认证已完成，计费结果未知（任务被取消或中断）"
                                 if outcome.success else
                                 "任务被取消或中断，认证未完成")
            _persist(task_id, username, server_name, outcome)


def _persist(task_id: str, username: str, server_name: str, outcome: TaskOutcome) -> None:
    """写入或更新测试结果（以 task_id + username 唯一）。"""
    dao.upsert_result({
        "task_id": task_id,
        "username": username,
        "server": server_name,
        "test_time": time_util.format_log_time(),
        "online": outcome.online,
        "success": outcome.success,
        "status": outcome.status,
        "response_time": round(outcome.response_time, 3),
        "error": outcome.error,
    })
