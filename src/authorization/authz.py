# -*- coding: utf-8 -*-
"""
授权（Authorization）模块。

说明：
    RADIUS 协议中授权不是一个独立请求阶段，
    服务器通过 Access-Accept 携带的授权属性完成授权下发。

本模块职责：
    1. 从 Access-Accept 中提取常见授权属性；
    2. 输出结构化授权结果，供测试结果与解析页面展示。

常见授权属性：
    Session-Timeout(27)     会话超时
    Idle-Timeout(28)        空闲超时
    Termination-Action(29)  终止动作
    Filter-Id(11)           过滤规则
    Class(50)               分类标识
    Tunnel-Type(64)         隧道类型
    Tunnel-Medium-Type(65)  隧道介质
    Tunnel-Private-Group-ID(81)  隧道 VLAN
    Acct-Interim-Interval(85)    计费间隔
    Service-Type(6)         服务类型
"""

from typing import List

from ..radius.codes import (
    ATTR_ACCT_INTERIM_INTERVAL,
    ATTR_CALLED_STATION_ID,
    ATTR_CALLING_STATION_ID,
    ATTR_NAS_IDENTIFIER,
    TYPE_INTEGER,
    decode_value,
)

# 需要提取的授权属性：编号 -> (英文名称, 中文名称, 类型)
AUTHORIZATION_ATTRIBUTES = {
    6: ("Service-Type", "服务类型", TYPE_INTEGER),
    11: ("Filter-Id", "过滤规则标识", "string"),
    27: ("Session-Timeout", "会话超时（秒）", TYPE_INTEGER),
    28: ("Idle-Timeout", "空闲超时（秒）", TYPE_INTEGER),
    29: ("Termination-Action", "终止动作", TYPE_INTEGER),
    50: ("Class", "分类标识", "octets"),
    64: ("Tunnel-Type", "隧道类型", TYPE_INTEGER),
    65: ("Tunnel-Medium-Type", "隧道介质类型", TYPE_INTEGER),
    81: ("Tunnel-Private-Group-ID", "隧道私有组标识（VLAN）", "string"),
    85: ("Acct-Interim-Interval", "计费间隔（秒）", TYPE_INTEGER),
    88: ("Framed-Pool", "地址池", "string"),
}

# 已知的 Service-Type 取值
SERVICE_TYPE_NAMES = {
    1: "Login",
    2: "Framed",
    3: "Callback Login",
    4: "Callback Framed",
    5: "Outbound",
    6: "Administrative",
    7: "NAS Prompt",
    8: "Authenticate Only",
    9: "Callback NAS Prompt",
    10: "Call Check",
    11: "Callback Administrative",
}

# 已知的 Termination-Action 取值
TERMINATION_ACTION_NAMES = {0: "Default", 1: "RADIUS-Request"}


def extract(packet) -> List[dict]:
    """
    从 Access-Accept 报文中提取授权属性。

    参数：
        packet: RadiusPacket 对象

    返回：
        授权属性列表，每项含 attribute_id、name、name_zh、type、value、description。
    """
    result = []
    if packet is None:
        return result
    for attr in packet.attributes:
        if attr.is_vsa:
            continue
        definition = AUTHORIZATION_ATTRIBUTES.get(attr.attr_id)
        if definition is None:
            continue
        name, name_zh, type_name = definition
        value = decode_value(type_name, attr.raw)
        result.append({
            "attribute_id": attr.attr_id,
            "name": name,
            "name_zh": name_zh,
            "type": type_name,
            "value": value,
            "description": describe(attr.attr_id, value),
        })
    return result


def describe(attr_id: int, value) -> str:
    """
    把已知枚举值翻译为中文说明。

    参数：
        attr_id: 属性编号
        value: 属性值

    返回：
        说明文字；无对应枚举时返回空字符串。
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""
    if attr_id == 6:
        return SERVICE_TYPE_NAMES.get(number, "未知(%d)" % number)
    if attr_id == 29:
        return TERMINATION_ACTION_NAMES.get(number, "未知(%d)" % number)
    if attr_id == 27 or attr_id == 28:
        return "%d 秒" % number
    if attr_id == 85:
        return "%d 秒" % number
    return ""


def has_authorization(packet) -> bool:
    """判断响应报文是否携带了授权属性。"""
    return len(extract(packet)) > 0
