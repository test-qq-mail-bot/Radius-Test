# -*- coding: utf-8 -*-
"""
单次认证测试落库模块。

适用链路：
    用户管理-用户列表「测试」、RADIUS Server「Radius 用户测试」，
    即 /api/servers/{name}/auth-test 与 batch-auth-test 这两类单次探测。

规则：
    1. 仅在系统配置「保存 RADIUS 报文」开启时落库（关闭时结果只显示在弹窗）；
    2. 每个用户只保留最新一份：写入前清理该用户上一次的单次测试记录；
    3. 批量/性能测试任务走 testing.session / testing.task 链路，
       报文按轮次全量保存，不受本模块的保留策略影响。
"""

from ..common import time_util, uuid_util
from ..database import dao
from ..logging import logger
from ..parser import packet_parser
from . import packets as packets_mod
from . import state as state_mod

# 单次测试任务 ID 前缀，用于与批量/性能测试任务区分
SINGLE_TASK_PREFIX = "UT-"


def new_task_id() -> str:
    """生成单次测试的任务 ID。"""
    return "%s%s" % (SINGLE_TASK_PREFIX, uuid_util.new_task_id())


def _status(result) -> str:
    """按认证结果判定结果状态。"""
    if result.response_packet is None:
        return state_mod.TIMEOUT if "超时" in (result.error or "") else state_mod.FAILED
    return state_mod.SUCCESS if result.success else state_mod.FAILED


def persist_single_test(server: dict, username: str, protocol: str, result):
    """
    落库一次单次测试（结果 + 报文 + 属性）。

    参数：
        server: RADIUS Server 配置
        username: 用户名
        protocol: 认证协议
        result: RadiusClient.authenticate 的返回对象

    返回：
        任务 ID；未落库时返回空串。
    """
    task_id = new_task_id()
    server_name = str(server.get("name") or server.get("server_address") or "")
    # 每个用户只保留最新一份：先清理该用户上一次的单次测试记录
    dao.delete_single_test(username)
    dao.save_result({
        "task_id": task_id,
        "username": username,
        "server": server_name,
        "test_time": time_util.format_log_time(),
        "online": False,
        "success": bool(result.success),
        "status": _status(result),
        "response_time": round(result.response_time_ms, 3),
        "error": result.error or "",
    })
    request_packet = result.request_packet
    response_packet = result.response_packet
    if request_packet is not None:
        packet_parser.enrich(request_packet)
    if response_packet is not None:
        packet_parser.enrich(response_packet)
    packets_mod.save_packets(task_id, username, server_name,
                             request_packet, response_packet)
    logger.debug("testing", "单次测试结果已落库", {
        "task_id": task_id,
        "username": username,
        "server": server_name,
        "protocol": protocol,
    })
    return task_id
