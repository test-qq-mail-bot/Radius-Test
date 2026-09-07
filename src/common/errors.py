# -*- coding: utf-8 -*-
"""
统一异常定义模块。

职责：
    定义项目内全部业务异常类型，便于上层模块统一捕获并转换为用户可读错误。

分层：
    RadiusTestError       —— 全部业务异常基类
    ├─ ConfigError        —— 配置错误（对应停止原因 CONFIG_ERROR）
    ├─ RadiusError        —— RADIUS 协议错误（对应 RADIUS_ERROR）
    ├─ TaskError          —— 任务错误（对应 TASK_ERROR）
    ├─ DictionaryError    —— 字典解析错误
    └─ ValidationError    —— 数据校验错误
"""


class RadiusTestError(Exception):
    """业务异常基类。"""

    def __init__(self, message: str = "", detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        if self.detail:
            return "%s；%s" % (self.message, self.detail)
        return self.message


class ConfigError(RadiusTestError):
    """配置读取、校验或写入失败。"""


class RadiusError(RadiusTestError):
    """RADIUS 报文构造、发送、接收或校验失败。"""


class RadiusTimeout(RadiusError):
    """RADIUS 请求超时未收到响应。"""

    def __init__(self, message: str = "RADIUS 请求超时", detail: str = ""):
        super().__init__(message, detail)


class TaskError(RadiusTestError):
    """测试任务创建、执行或取消失败。"""


class DictionaryError(RadiusTestError):
    """Dictionary 模板解析、加载或校验失败。"""


class ValidationError(RadiusTestError):
    """输入数据校验失败。"""


class CertificateError(RadiusTestError):
    """HTTPS 证书生成、加载或校验失败。"""
