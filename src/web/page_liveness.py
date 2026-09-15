# -*- coding: utf-8 -*-
"""
测试页面存活看门狗模块。

职责：
    为「测试是否应当继续运行」提供唯一判据——**前端是否仍停在测试页面**。

判据（需求5）：
    1. 测试页面（性能测试 perf / Radius 用户测试 server）每 HEARTBEAT_INTERVAL
       秒调用一次 POST /api/tasks/heartbeat 上报存活，刷新存活时间；
    2. 前端在本应用内跳到非测试页面时，渲染新页面即会上报一次该页面标识，
       后端据此立即中断测试（原因 PAGE_LEFT），不等超时；
       POST /api/tasks/leave 用于需要显式声明离开的场景，效果相同；
    3. 关闭标签页 / 关闭浏览器 / 断网时心跳自然停止，
       超过 PAGE_TIMEOUT 秒未上报即判定测试页面已失联，立即中断（HEARTBEAT_TIMEOUT）。

说明：
    窗口切到后台不算离开——前端不监听 visibilitychange / blur，
    页面心跳由定时器继续发送，后台标签页上的测试不会被打断。

    仅通过接口启动、从未有测试页面上报过存活的场景不启用保护，
    以免影响自动化调用（与旧版保护取向一致）。

    本模块取代了旧版「WebSocket 心跳 / 浏览器连接断开」判据：
    WebSocket 只负责实时数据推送与连接保活，不再参与测试存活判定。
"""

import asyncio
import time
from typing import Optional

from ..logging import logger

# 测试页面标识：只有这些页面上的测试才允许持续运行
TEST_PAGES = ("perf", "server")
# 测试页面上报存活的时间间隔（秒），与前端 PAGE_HEARTBEAT_INTERVAL 保持一致
HEARTBEAT_INTERVAL = 2.0
# 存活超时（秒）：超过该时长没有任何测试页面上报，即判定页面已离开。
# 取 2 个上报周期，容忍一次抖动，同时保证「检测不到就尽快中断」。
PAGE_TIMEOUT = 4.0
# 看门狗轮询间隔（秒）
POLL_INTERVAL = 1.0

# 最近一次测试页面存活上报时刻（monotonic），0 表示未上报或已离开
_alive_at = 0.0
# 最近一次上报存活时所在的页面
_page = ""
# 是否曾经有测试页面上报过存活（决定保护是否启用）
_activated = False
_watch_task: Optional[asyncio.Task] = None


def mark_alive(page: str) -> None:
    """记录一次测试页面存活上报，刷新存活时间。"""
    global _alive_at, _page, _activated
    _alive_at = time.monotonic()
    _page = str(page or "")
    _activated = True


def mark_left(page: str = "") -> None:
    """
    记录测试页面已离开：立即失效并解除保护。

    解除保护是必须的：否则「已离开」之后新启动的测试会被残留的
    失效标记直接判为 HEARTBEAT_TIMEOUT（实测缺陷）。
    真正的失联场景（关标签页 / 关浏览器 / 断网）不会走到这里，
    保护仍然启用，由超时兜底。
    """
    global _alive_at, _page, _activated
    _alive_at = 0.0
    _page = ""
    _activated = False
    logger.info("web", "测试页面已离开", {"page": str(page or "") or "-"})


def report(page: str) -> str:
    """
    处理一次页面上报，返回结论。

    参数：
        page: 当前前端页面标识（如 perf / server / home / result）

    返回：
        "alive"   测试页面，已刷新存活时间
        "left"    非测试页面且保护已启用，调用方应立即中断测试
        "ignored" 非测试页面且保护未启用，忽略
    """
    if str(page or "") in TEST_PAGES:
        mark_alive(page)
        return "alive"
    if _activated:
        mark_left(page)
        return "left"
    return "ignored"


def current_page() -> str:
    """返回最近一次上报存活所在的页面。"""
    return _page


def activated() -> bool:
    """保护是否已启用（曾有测试页面上报过存活）。"""
    return _activated


def alive() -> bool:
    """测试页面当前是否存活（未超时）。"""
    return bool(_alive_at) and (time.monotonic() - _alive_at) <= PAGE_TIMEOUT


def expired() -> bool:
    """测试页面是否已失联（保护已启用且存活超时）。"""
    return _activated and not alive()


def reset() -> None:
    """清空页面存活状态。"""
    global _alive_at, _page, _activated
    _alive_at = 0.0
    _page = ""
    _activated = False


def _has_running_test() -> bool:
    """是否存在需要页面存活的测试：性能测试会话或账号认证测试在线会话。"""
    from . import runtime

    session = runtime.get_session()
    if session is not None and getattr(session, "running", False):
        return True
    return runtime.user_test_count() > 0


async def stop_all_tests(reason: str) -> int:
    """
    按指定原因中断全部测试（性能测试 + 账号认证测试）。

    参数：
        reason: 停止原因，必须是 testing.state.STOP_REASONS 之一

    返回：
        实际中断的测试数量（性能测试计 1，账号认证测试按在线会话数计）。
    """
    from ..testing import state as state_mod
    from . import runtime, user_test

    stopped = 0
    session = runtime.get_session()
    if session is not None and getattr(session, "running", False):
        try:
            await session.stop(reason)
            runtime.clear_session()
            stopped += 1
        except Exception as exc:
            logger.error("web", "中断性能测试失败", {"error": str(exc)}, exc_info=True)
    try:
        stopped += await user_test.stop_user_tests()
    except Exception as exc:
        logger.warning("web", "中断账号认证测试失败", {"error": str(exc)})
    if stopped:
        logger.info("web", "已按页面存活判据中断测试", {
            "reason": state_mod.stop_reason_text(reason),
            "count": stopped,
        })
    return stopped


async def start_watch() -> None:
    """启动看门狗任务。"""
    global _watch_task
    if _watch_task is not None and not _watch_task.done():
        return
    _watch_task = asyncio.create_task(_watch())


async def stop_watch() -> None:
    """停止看门狗任务。"""
    global _watch_task
    if _watch_task is None:
        return
    _watch_task.cancel()
    try:
        await _watch_task
    except (asyncio.CancelledError, Exception):
        pass
    _watch_task = None


async def _watch() -> None:
    """看门狗循环：测试页面失联且有测试在跑时立即中断。"""
    from ..testing import state as state_mod

    while True:
        try:
            await asyncio.sleep(POLL_INTERVAL)
            if not expired():
                continue
            if not _has_running_test():
                continue
            page = _page or "-"
            # 先取消失效标记，避免中断过程中被重复判定
            reset()
            logger.warning("web", "测试页面心跳超时，立即中断测试", {
                "timeout": PAGE_TIMEOUT,
                "page": page,
            })
            await stop_all_tests(state_mod.HEARTBEAT_TIMEOUT)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("web", "页面存活看门狗异常", {"error": str(exc)}, exc_info=True)
            await asyncio.sleep(1.0)
