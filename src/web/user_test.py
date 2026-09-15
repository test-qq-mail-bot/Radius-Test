# -*- coding: utf-8 -*-
"""
单用户账号认证测试模块（会话化，保持在线）。

适用链路（需求3/5）：
    用户管理-用户列表「测试」/「批量测试」、RADIUS Server「Radius 用户测试」。
    即 /api/servers/{name}/auth-test 与 /batch-auth-test。

行为：
    1. 复用 testing.task.run_user_task 完成「认证 -> 计费 Start -> 后台 Interim 保活」；
    2. 认证并计费上线成功后，会话保存在 runtime.user_test_manager 中保持在线，
       直到用户点击「停止测试」或前端断开（见 ws.py）时才发送 Accounting-Stop；
    3. 与性能测试（runtime.current_session）互斥，二者不允许同时进行。

说明：
    与 testing.single.persist_single_test 的区别：后者是「单次探测」，
    认证完即结束、不保持在线；本模块用于「测试后保持在线」的新口径。
"""

from ..common import errors
from ..config import loader
from ..database import dao
from ..logging import logger
from ..radius import builder as radius_builder
from ..radius.client import RadiusClient
from ..testing import single as single_mod
from ..testing import task as task_mod
from . import runtime


class UserTestError(Exception):
    """单用户认证测试的请求级错误（由 API 层转换为 400）。"""


def ensure_no_perf_test() -> None:
    """
    互斥预检查：性能测试运行中时禁止发起账号认证测试。

    批量测试在循环开始前调用一次，避免部分用户已上线后才报错。
    """
    perf = runtime.get_session()
    if perf is not None and getattr(perf, "running", False):
        raise UserTestError("性能测试正在运行，请先停止后再进行账号认证测试")


def _find_server(name: str):
    """按名称查找 RADIUS Server 配置。"""
    for server in loader.get_servers():
        if server.get("name") == name:
            return server
    return None


def _normalize_dot1x(raw):
    """复用性能测试的 Dot1X 规范化口径，保证前后端字段处理一致。"""
    from .api_task import _normalize_dot1x as normalize
    return normalize(raw)


def _ensure_manager(server: dict):
    """
    懒创建并返回单用户测试的在线会话管理器。

    Interim-Update 间隔取 Server 的「计费间隔」，为 0 时回退 60 秒；
    掉线判定阈值与计费超时/重试沿用全局测试配置。
    """
    from ..accounting import acct as acct_mod

    config = loader.load_config()
    test_conf = config.get("test") or {}
    save_packets = bool((config.get("storage") or {}).get("save_packets"))
    manager = runtime.get_user_test_manager()
    if manager is not None:
        # 管理器为进程级单例：按最新配置刷新「保存报文」开关，避免沿用旧值
        manager.set_save_packets(save_packets)
        return manager
    interim_interval = int(server.get("accounting_interval") or 0) or 60
    manager = acct_mod.OnlineSessionManager(
        RadiusClient(runtime.socket_manager),
        interim_interval,
        int(test_conf.get("interim_max_fail") or 3),
        float(test_conf.get("accounting_timeout") or 1.0),
        int(test_conf.get("accounting_retry_count") or 1),
        save_packets,
    )
    runtime.set_user_test_manager(manager)
    logger.info("api", "单用户认证测试在线管理器已创建", {
        "interim_interval": interim_interval,
    })
    return manager


async def start_user_test(name: str, username: str, password: str,
                          protocol: str, dot1x_raw=None,
                          save_packets: bool = None) -> dict:
    """
    执行一次「保持在线」的单用户账号认证测试。

    返回与旧探测口径一致的结果字典，并附带 task_id / session_id / online，
    供前端登记到「停止测试」状态条。

    异常：
        UserTestError: 互斥冲突 / Server 不存在等请求级错误。
    """
    # 互斥：性能测试运行中不允许再发起账号认证测试
    perf = runtime.get_session()
    if perf is not None and getattr(perf, "running", False):
        raise UserTestError("性能测试正在运行，请先停止后再进行账号认证测试")

    server = _find_server(name)
    if server is None:
        raise UserTestError("RADIUS Server 不存在")

    manager = _ensure_manager(server)
    await manager.start()

    config = loader.load_config()
    if save_packets is None:
        save_packets = bool((config.get("storage") or {}).get("save_packets"))
    test_conf = config.get("test") or {}

    # 每个用户仅保留最新一份单次测试记录（结果 + 报文），避免旧数据残留
    task_id = single_mod.new_task_id()
    try:
        dao.delete_single_test(username)
    except Exception as exc:
        logger.debug("api", "清理单次测试旧记录失败（已忽略）", {
            "username": username, "error": str(exc),
        })

    # 统一口径：账号认证测试与性能测试共用 builder.resolve_dot1x，
    # 所有可留空字段（NAS-Port / NAS-Port-Id / 终端 MAC / NAS-Identifier /
    # Service-Type / Framed-IP-Address / Connect-Info）
    # 一律补齐默认合法值后发送，不存在「留空不发送」。
    dot1x = radius_builder.resolve_dot1x(_normalize_dot1x(dot1x_raw))

    try:
        outcome = await task_mod.run_user_task(
            RadiusClient(runtime.socket_manager),
            server, username, password, protocol, task_id,
            bool(save_packets), manager,
            enable_accounting=True,
            online_criteria="accounting",
            accounting_timeout=float(test_conf.get("accounting_timeout") or 1.0),
            accounting_retry_count=int(test_conf.get("accounting_retry_count") or 1),
            accounting_message_authenticator=bool(
                test_conf.get("accounting_message_authenticator")),
            dot1x=dot1x,
        )
    except errors.RadiusError as exc:
        raise UserTestError(str(exc))

    session_id = outcome.session_id if outcome.online else ""
    if session_id:
        # 重复点击同一用户测试：先停掉上一次仍保持的会话，避免旧会话无限期发送 Interim
        previous = runtime.get_user_test_session_by_username(username)
        if previous and previous != session_id:
            await manager.stop_session(previous)
            runtime.remove_user_test_session(previous)
        runtime.add_user_test_session(session_id, {
            "username": username,
            "server_name": server.get("name"),
            "task_id": task_id,
        })

    result = {
        "server": server.get("server_address"),
        "authentication_port": server.get("authentication_port"),
        "accounting_port": server.get("accounting_port"),
        "connect_result": "可达" if outcome.success else "失败",
        "radius_result": "Access-Accept" if outcome.success else "Access-Reject",
        "response_time_ms": round(outcome.response_time, 3),
        "error": outcome.error or "",
        "task_id": task_id,
        "session_id": session_id,
        "online": bool(outcome.online),
    }
    logger.info("api", "账号认证测试完成（保持在线）", {
        "server": name, "username": username,
        "result": result["radius_result"],
        "online": result["online"],
    })
    return result


async def stop_user_tests() -> int:
    """
    停止全部单用户/批量账号认证测试：发送 Accounting-Stop 并清理登记表。

    返回：
        成功发送 Accounting-Stop 的会话数量。
    """
    manager = runtime.get_user_test_manager()
    count = 0
    if manager is not None:
        count = await manager.stop_all()
    runtime.clear_user_test_sessions()
    if count:
        logger.info("api", "账号认证测试已停止", {"stopped": count})
    return count
