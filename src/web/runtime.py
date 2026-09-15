# -*- coding: utf-8 -*-
"""
运行时全局状态模块。

职责：
    集中保存进程级共享对象，避免各 API 模块之间循环引用。

包含：
    socket_manager: UDP Socket 池管理器
    ws_manager: WebSocket 连接管理器
    current_session: 当前测试会话，无测试时为 None
    user_test_manager: 单用户账号认证测试的在线会话管理器（保持在线）
    user_test_sessions: 单用户测试在线会话登记表（session_id -> 信息）
    disconnect_listener: Disconnect-Request 监听器（RFC 5176，需求4）
"""

from typing import Dict, Optional

from ..radius.socket_pool import SocketPoolManager

socket_manager = SocketPoolManager()
ws_manager = None  # 由 app 初始化时赋值
current_session = None  # type: Optional[object]
disconnect_listener = None  # type: Optional[object]
# 单用户/批量账号认证测试：会话化管理器（保持在线）与在线会话登记表。
# 与性能测试（current_session）互斥：二者不允许同时进行（需求3/5）。
user_test_manager = None  # type: Optional[object]
user_test_sessions: Dict[str, dict] = {}
# 监听地址与协议信息，由 main 启动时写入
listen_info = {
    "hosts": [],
    "port": 0,
    "https": True,
    "local_only": True,
    "warning": "",
}


def set_ws_manager(manager) -> None:
    """设置 WebSocket 管理器。"""
    global ws_manager
    ws_manager = manager


def get_session():
    """返回当前测试会话。"""
    return current_session


def set_session(session) -> None:
    """设置当前测试会话。"""
    global current_session
    current_session = session


def clear_session() -> None:
    """清空当前测试会话。"""
    global current_session
    current_session = None


def set_disconnect_listener(listener) -> None:
    """设置 Disconnect-Request 监听器。"""
    global disconnect_listener
    disconnect_listener = listener


def get_disconnect_listener():
    """返回 Disconnect-Request 监听器。"""
    return disconnect_listener


# ---------------- 单用户账号认证测试（需求3/5） ----------------

def get_user_test_manager():
    """返回单用户测试的在线会话管理器。"""
    return user_test_manager


def set_user_test_manager(manager) -> None:
    """设置单用户测试的在线会话管理器。"""
    global user_test_manager
    user_test_manager = manager


def add_user_test_session(session_id: str, info: dict) -> None:
    """登记一个单用户测试在线会话。"""
    if session_id:
        user_test_sessions[session_id] = dict(info or {})


def remove_user_test_session(session_id: str) -> None:
    """移除一个单用户测试在线会话登记。"""
    user_test_sessions.pop(session_id, None)


def get_user_test_session_by_username(username: str) -> str:
    """按用户名查找其当前在线会话的 session_id，未找到返回空串。"""
    for session_id, info in user_test_sessions.items():
        if info.get("username") == username:
            return session_id
    return ""


def user_test_count() -> int:
    """当前单用户测试在线会话数量。"""
    return len(user_test_sessions)


def clear_user_test_sessions() -> None:
    """清空单用户测试在线会话登记表（不发送 Stop）。"""
    user_test_sessions.clear()
