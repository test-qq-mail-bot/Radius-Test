# -*- coding: utf-8 -*-
"""
数据校验工具模块。

职责：
    提供输入合法性校验，避免非法数据进入 RADIUS 报文构造或数据库。

说明：
    全部校验函数只返回布尔值或抛出异常，不做自动修正，
    避免静默篡改用户输入。
"""

import re
from typing import Any, List

from .errors import ValidationError
from .net_util import is_valid_ip

# 用户名允许字符：字母、数字、以及常见域名与分隔符
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._@\\\-\u4e00-\u9fa5]+$")

# 模板名允许字符：字母、数字、下划线、短横线
_TEMPLATE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")


def is_valid_username(value: Any) -> bool:
    """校验用户名合法性（非空、长度不超过 253、字符受限）。"""
    if not isinstance(value, str):
        return False
    v = value.strip()
    if not v or len(v) > 253:
        return False
    return bool(_USERNAME_PATTERN.match(v))


def is_valid_password(value: Any) -> bool:
    """校验密码合法性（非空字符串，长度不超过 256）。"""
    if not isinstance(value, str):
        return False
    return 0 < len(value) <= 256


def is_valid_port(value: Any) -> bool:
    """校验端口号合法性（1~65535 的整数）。"""
    try:
        port = int(value)
    except (TypeError, ValueError):
        return False
    return 1 <= port <= 65535


def is_valid_timeout(value: Any) -> bool:
    """校验超时时间合法性（0.1~120 秒）。"""
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return False
    return 0.1 <= timeout <= 120.0


def is_valid_positive_int(value: Any, maximum: int = None) -> bool:
    """校验正整数合法性，可指定上限。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return False
    if number <= 0:
        return False
    if maximum is not None and number > maximum:
        return False
    return True


def is_valid_host(value: Any) -> bool:
    """校验主机地址合法性（IP 或主机名）。"""
    if not isinstance(value, str) or not value.strip():
        return False
    v = value.strip()
    if is_valid_ip(v):
        return True
    if len(v) > 253:
        return False
    return bool(re.match(r"^[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?$", v))


def is_valid_template_name(value: Any) -> bool:
    """校验 Dictionary 模板名合法性。"""
    if not isinstance(value, str):
        return False
    v = value.strip()
    if not v or len(v) > 64:
        return False
    return bool(_TEMPLATE_NAME_PATTERN.match(v))


def is_valid_vendor_id(value: Any) -> bool:
    """校验 Vendor-ID 合法性（1~4294967295）。"""
    try:
        vendor_id = int(value)
    except (TypeError, ValueError):
        return False
    return 1 <= vendor_id <= 0xFFFFFFFF


def is_valid_attribute_id(value: Any) -> bool:
    """校验属性编号合法性（0~255，VSA 子类型同样使用 0~255）。"""
    try:
        attr_id = int(value)
    except (TypeError, ValueError):
        return False
    return 0 <= attr_id <= 255


def require(condition: bool, message: str, detail: str = "") -> None:
    """条件不满足时抛出 ValidationError。"""
    if not condition:
        raise ValidationError(message, detail)


def require_in(value: Any, allowed: List[Any], field: str) -> None:
    """值必须属于允许列表，否则抛出 ValidationError。"""
    if value not in allowed:
        raise ValidationError(
            "%s 取值非法" % field,
            "实际=%s；允许=%s" % (value, allowed),
        )
