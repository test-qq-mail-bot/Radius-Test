# -*- coding: utf-8 -*-
"""
标识生成模块。

职责：
    生成任务 ID、会话 ID、RADIUS 计费会话 ID 等唯一标识。

说明：
    统一使用 Python 标准库 uuid，不引入第三方依赖。
"""

import uuid


def new_task_id() -> str:
    """生成测试任务 ID（32 位十六进制）。"""
    return uuid.uuid4().hex


def new_session_id() -> str:
    """生成进程内会话 ID（32 位十六进制）。"""
    return uuid.uuid4().hex


def new_radius_session_id(prefix: str = "RT") -> str:
    """
    生成 RADIUS Acct-Session-Id。

    参数：
        prefix: 前缀，便于在服务器上区分测试流量

    返回：
        长度不超过 32 的字符串（RFC 2866 未强制长度，但多数实现限制 32 字节）。
    """
    return "%s%s" % (prefix, uuid.uuid4().hex[:30])


def short_id(length: int = 8) -> str:
    """生成短标识，用于日志与前端展示。"""
    return uuid.uuid4().hex[:length]
