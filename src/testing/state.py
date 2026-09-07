# -*- coding: utf-8 -*-
"""
测试状态与停止原因定义模块。

职责：
    定义固定的 7 种测试状态与 8 类停止原因（项目书 15.1 / 15.2）。
"""

# ---------------- 7 种测试状态 ----------------
PENDING = "PENDING"
RUNNING = "RUNNING"
SUCCESS = "SUCCESS"
FAILED = "FAILED"
TIMEOUT = "TIMEOUT"
CANCELLED = "CANCELLED"
ABORTED = "ABORTED"

TEST_STATES = (PENDING, RUNNING, SUCCESS, FAILED, TIMEOUT, CANCELLED, ABORTED)

# ---------------- 8 类停止原因 ----------------
USER_STOP = "USER_STOP"
HEARTBEAT_TIMEOUT = "HEARTBEAT_TIMEOUT"
BROWSER_DISCONNECTED = "BROWSER_DISCONNECTED"
RESOURCE_LIMIT = "RESOURCE_LIMIT"
TASK_ERROR = "TASK_ERROR"
CONFIG_ERROR = "CONFIG_ERROR"
RADIUS_ERROR = "RADIUS_ERROR"
SYSTEM_ERROR = "SYSTEM_ERROR"

STOP_REASONS = (
    USER_STOP,
    HEARTBEAT_TIMEOUT,
    BROWSER_DISCONNECTED,
    RESOURCE_LIMIT,
    TASK_ERROR,
    CONFIG_ERROR,
    RADIUS_ERROR,
    SYSTEM_ERROR,
)

# 停止原因中文说明，供页面展示
STOP_REASON_TEXT = {
    USER_STOP: "用户手动停止",
    HEARTBEAT_TIMEOUT: "心跳超时，前端失去响应",
    BROWSER_DISCONNECTED: "浏览器断开连接",
    RESOURCE_LIMIT: "达到任务数量上限，停止新增任务",
    TASK_ERROR: "测试任务执行异常",
    CONFIG_ERROR: "配置错误",
    RADIUS_ERROR: "RADIUS 协议错误",
    SYSTEM_ERROR: "系统内部错误",
}

# 测试状态中文说明
TEST_STATE_TEXT = {
    PENDING: "等待中",
    RUNNING: "进行中",
    SUCCESS: "成功",
    FAILED: "失败",
    TIMEOUT: "超时",
    CANCELLED: "已取消",
    ABORTED: "已终止",
}

# 会话级别状态（写入 test_sessions.status）
SESSION_RUNNING = "RUNNING"
SESSION_COMPLETED = "COMPLETED"
SESSION_STOPPED = "STOPPED"
SESSION_ABORTED = "ABORTED"


def state_text(state: str) -> str:
    """返回测试状态中文说明。"""
    return TEST_STATE_TEXT.get(state, state)


def stop_reason_text(reason: str) -> str:
    """返回停止原因中文说明。"""
    return STOP_REASON_TEXT.get(reason, reason)
