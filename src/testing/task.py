# -*- coding: utf-8 -*-
"""
单用户测试任务模块。

职责：
    执行一次完整的 dot1x 用户登录模拟：
        认证 -> 授权属性提取 -> 计费上线 -> 结果记录 -> 报文保存

结果判定（用户确认口径）：
    成功：Access-Accept 且 Accounting-Start 成功 -> 在线
    失败：认证失败（Access-Reject / 超时 / 协议错误）
    掉线：上线后连续 interim_max_fail 次 Interim-Update 失败
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
                 "error", "authorization", "session_id")

    def __init__(self):
        self.username = ""
        self.success = False
        self.online = False
        self.status = state_mod.PENDING
        self.response_time = 0.0
        self.error = ""
        self.authorization = []
        self.session_id = ""


# 报文与属性落库由 packets 模块统一提供（与单次测试链路复用）


async def run_user_task(client, server: dict, username: str, password: str,
                        protocol: str, task_id: str, save_packets: bool,
                        online_manager: "acct_mod.OnlineSessionManager" = None,
                        enable_accounting: bool = True,
                        peer_challenge_bytes: int = 8) -> TaskOutcome:
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

    返回：
        TaskOutcome 对象。
    """
    outcome = TaskOutcome()
    outcome.username = username
    server_name = str(server.get("name") or server.get("server_address") or "")
    started = time.time()
    try:
        result = await client.authenticate(server, username, password, protocol,
                                           peer_challenge_bytes)
    except Exception as exc:
        outcome.status = state_mod.FAILED
        outcome.error = "认证异常；%s" % exc
        logger.error("testing", "认证异常", {"username": username, "error": str(exc)},
                     exc_info=True)
        _persist(task_id, username, server_name, outcome)
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
        outcome.status = state_mod.TIMEOUT if "超时" in (result.error or "") else state_mod.FAILED
        outcome.error = result.error or "认证失败"
        outcome.success = False
        _persist(task_id, username, server_name, outcome)
        return outcome

    # 认证成功，提取授权属性
    outcome.authorization = authz.extract(response_packet)

    # 计费上线
    if enable_accounting:
        session_id = uuid_util.new_radius_session_id()
        outcome.session_id = session_id
        try:
            acct_result = await client.send_accounting(server, username, 1, session_id)
        except Exception as exc:
            acct_result = None
            outcome.error = "计费上线异常；%s" % exc
        succeeded = bool(acct_result and acct_result.success)
        if succeeded and online_manager is not None:
            await online_manager.add(acct_mod.OnlineSession(
                username=username,
                server_name=server_name,
                session_id=session_id,
                protocol=protocol,
                task_id=task_id,
            ))
        outcome.online = succeeded
        outcome.success = succeeded
        outcome.status = state_mod.SUCCESS if succeeded else state_mod.FAILED
        if not succeeded and not outcome.error:
            outcome.error = "计费上线失败"
    else:
        outcome.success = True
        outcome.online = False
        outcome.status = state_mod.SUCCESS

    _persist(task_id, username, server_name, outcome)
    return outcome


def _persist(task_id: str, username: str, server_name: str, outcome: TaskOutcome) -> None:
    """保存测试结果到数据库。"""
    dao.save_result({
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
