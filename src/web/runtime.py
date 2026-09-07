# -*- coding: utf-8 -*-
"""
运行时全局状态模块。

职责：
    集中保存进程级共享对象，避免各 API 模块之间循环引用。

包含：
    socket_manager: UDP Socket 池管理器
    ws_manager: WebSocket 连接管理器
    current_session: 当前测试会话，无测试时为 None
"""

from typing import Optional

from ..radius.socket_pool import SocketPoolManager

socket_manager = SocketPoolManager()
ws_manager = None  # 由 app 初始化时赋值
current_session = None  # type: Optional[object]
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
