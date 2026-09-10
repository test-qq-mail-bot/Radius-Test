# -*- coding: utf-8 -*-
"""
授权（Authorization）模块。

说明：
    RADIUS 协议中授权不是一个独立请求阶段，
    服务器通过 Access-Accept 携带的授权属性完成授权下发。

本模块职责：
    1. 从 Access-Accept 中提取授权属性（含厂商私有属性 VSA）；
    2. 给出属性分类（隧道/VLAN、QoS 限速、安全组/ACL、会话控制、其它）；
    3. 输出可直接上屏的展示值（速率类属性从 bit/s 换算为 Kbps / Mbps）。

常见授权属性来源：
    RFC2865 / RFC2866：Tunnel-Type、Tunnel-Medium-Type、
        Tunnel-Private-Group-ID、Session-Timeout、Idle-Timeout、Filter-Id 等
    Huawei(2011)：HW-UCL-Group（安全组）、HW-Forwarding-VLAN、
        HW-Input/Output-Committed/Peak-Information-Rate（上下行限速）、
        HW-Up/Down-Priority（802.1p）、HW-Redirect-ACL 等
"""

from typing import Dict, List, Optional, Tuple

from ..radius.codes import (
    ATTR_ACCT_INTERIM_INTERVAL,
    TYPE_INTEGER,
)

# ---------------- 属性分类 ----------------
CATEGORY_VLAN = "vlan"
CATEGORY_QOS = "qos"
CATEGORY_SECURITY = "security"
CATEGORY_TIMEOUT = "timeout"
CATEGORY_OTHER = "other"

CATEGORY_TEXT = {
    CATEGORY_VLAN: "隧道 / VLAN",
    CATEGORY_QOS: "QoS 限速",
    CATEGORY_SECURITY: "安全组 / ACL",
    CATEGORY_TIMEOUT: "会话控制",
    CATEGORY_OTHER: "其它授权",
}

# 上屏顺序
CATEGORY_ORDER = (
    CATEGORY_VLAN, CATEGORY_QOS, CATEGORY_SECURITY, CATEGORY_TIMEOUT, CATEGORY_OTHER,
)

# 单位
UNIT_BPS = "bps"
UNIT_BIT = "bit"
UNIT_SECOND = "s"
UNIT_NONE = ""

# 标准属性：编号 -> (英文名, 中文名, 类型, 分类, 单位, 说明)
STANDARD_ATTRIBUTES: Dict[int, Tuple[str, str, str, str, str, str]] = {
    6: ("Service-Type", "服务类型", TYPE_INTEGER, CATEGORY_OTHER, UNIT_NONE, ""),
    11: ("Filter-Id", "过滤规则标识", "string", CATEGORY_SECURITY, UNIT_NONE, ""),
    27: ("Session-Timeout", "会话超时", TYPE_INTEGER, CATEGORY_TIMEOUT, UNIT_SECOND, ""),
    28: ("Idle-Timeout", "空闲超时", TYPE_INTEGER, CATEGORY_TIMEOUT, UNIT_SECOND, ""),
    29: ("Termination-Action", "终止动作", TYPE_INTEGER, CATEGORY_TIMEOUT, UNIT_NONE, ""),
    50: ("Class", "分类标识", "octets", CATEGORY_OTHER, UNIT_NONE, ""),
    64: ("Tunnel-Type", "隧道类型", TYPE_INTEGER, CATEGORY_VLAN, UNIT_NONE, ""),
    65: ("Tunnel-Medium-Type", "隧道介质类型", TYPE_INTEGER, CATEGORY_VLAN, UNIT_NONE, ""),
    81: ("Tunnel-Private-Group-ID", "隧道私有组标识（VLAN）", "string",
         CATEGORY_VLAN, UNIT_NONE, "下发 VLAN 编号或 VLAN 名称"),
    85: ("Acct-Interim-Interval", "计费间隔", TYPE_INTEGER, CATEGORY_TIMEOUT,
         UNIT_SECOND, ""),
    88: ("Framed-Pool", "地址池", "string", CATEGORY_OTHER, UNIT_NONE, ""),
}

# 华为私有属性（vendor_id = 2011）：(厂商编号, 属性编号) -> 定义
HUWEI_VENDOR_ID = 2011
VENDOR_ATTRIBUTES: Dict[Tuple[int, int], Tuple[str, str, str, str, str, str]] = {
    (HUWEI_VENDOR_ID, 1): ("HW-Input-Peak-Information-Rate", "上行峰值速率",
                           TYPE_INTEGER, CATEGORY_QOS, UNIT_BPS, "用户接入到 NAS 的峰值速率"),
    (HUWEI_VENDOR_ID, 2): ("HW-Input-Committed-Information-Rate", "上行承诺速率",
                           TYPE_INTEGER, CATEGORY_QOS, UNIT_BPS, "保证能够通过的平均速率"),
    (HUWEI_VENDOR_ID, 3): ("HW-Input-Committed-Burst-Size", "上行承诺突发尺寸",
                           TYPE_INTEGER, CATEGORY_QOS, UNIT_BIT, ""),
    (HUWEI_VENDOR_ID, 4): ("HW-Output-Peak-Information-Rate", "下行峰值速率",
                           TYPE_INTEGER, CATEGORY_QOS, UNIT_BPS, "从 NAS 到用户的峰值速率"),
    (HUWEI_VENDOR_ID, 5): ("HW-Output-Committed-Information-Rate", "下行承诺速率",
                           TYPE_INTEGER, CATEGORY_QOS, UNIT_BPS, "保证能够通过的平均速率"),
    (HUWEI_VENDOR_ID, 6): ("HW-Output-Committed-Burst-Size", "下行承诺突发尺寸",
                           TYPE_INTEGER, CATEGORY_QOS, UNIT_BIT, ""),
    (HUWEI_VENDOR_ID, 17): ("HW-Subscriber-QoS-Profile", "用户 QoS 模板",
                            "string", CATEGORY_QOS, UNIT_NONE, ""),
    (HUWEI_VENDOR_ID, 31): ("HW-Qos-Data", "QoS 模板名",
                            "string", CATEGORY_QOS, UNIT_NONE, "流量监管模板名称"),
    (HUWEI_VENDOR_ID, 33): ("HW-VoiceVlan", "语音 VLAN 授权标记",
                            TYPE_INTEGER, CATEGORY_VLAN, UNIT_NONE, ""),
    (HUWEI_VENDOR_ID, 61): ("HW-Up-Priority", "上行 802.1p 优先级",
                            TYPE_INTEGER, CATEGORY_QOS, UNIT_NONE, ""),
    (HUWEI_VENDOR_ID, 62): ("HW-Down-Priority", "下行 802.1p 优先级",
                            TYPE_INTEGER, CATEGORY_QOS, UNIT_NONE, ""),
    (HUWEI_VENDOR_ID, 91): ("Queue-Profile", "队列模板",
                            "string", CATEGORY_QOS, UNIT_NONE, ""),
    (HUWEI_VENDOR_ID, 160): ("HW-UCL-Group", "安全组",
                             TYPE_INTEGER, CATEGORY_SECURITY, UNIT_NONE,
                             "华为 UCL 组（安全组）编号"),
    (HUWEI_VENDOR_ID, 161): ("HW-Forwarding-VLAN", "转发 VLAN",
                             "string", CATEGORY_VLAN, UNIT_NONE, ""),
    (HUWEI_VENDOR_ID, 173): ("HW-Redirect-ACL", "重定向 ACL",
                             "string", CATEGORY_SECURITY, UNIT_NONE, ""),
    (HUWEI_VENDOR_ID, 182): ("Down-QOS-Profile-Name", "下行 QoS 模板名",
                             "string", CATEGORY_QOS, UNIT_NONE, ""),
    (HUWEI_VENDOR_ID, 251): ("User-Group-Name", "用户组名",
                             "string", CATEGORY_SECURITY, UNIT_NONE, ""),
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


def classify(vendor_id, attribute_id) -> Optional[Tuple[str, str, str, str, str, str]]:
    """
    按属性编号取出定义。

    参数：
        vendor_id: 厂商编号；标准属性传 None / 0
        attribute_id: 属性编号

    返回：
        (英文名, 中文名, 类型, 分类, 单位, 说明)；未收录时返回 None。
    """
    if vendor_id:
        return VENDOR_ATTRIBUTES.get((int(vendor_id), int(attribute_id)))
    return STANDARD_ATTRIBUTES.get(int(attribute_id))


def category_text(category: str) -> str:
    """返回分类中文名。"""
    return CATEGORY_TEXT.get(category, CATEGORY_TEXT[CATEGORY_OTHER])


def format_speed(value) -> str:
    """
    把 bit/s 速率换算为易读文本。

    参数：
        value: 速率原文（整数或数字字符串），单位 bit/s

    返回：
        形如 "102.4 Mbps（102400 Kbps）" 的文本。
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    kbps = number / 1000.0
    if kbps >= 1000:
        return "%s Mbps（%s Kbps）" % (_trim(kbps / 1000.0), _trim(kbps))
    return "%s Kbps" % _trim(kbps)


def _trim(number: float) -> str:
    """去掉多余的小数位与末尾零。"""
    text = "%.3f" % number
    return text.rstrip("0").rstrip(".")


def format_value(unit: str, value, english_name: str = "") -> str:
    """
    生成上屏展示值。

    参数：
        unit: 单位（bps / bit / s / 空）
        value: 属性原文
        english_name: 英文属性名，用于少量枚举翻译（如 Service-Type）

    返回：
        展示文本。
    """
    if unit == UNIT_BPS:
        return format_speed(value)
    if unit == UNIT_SECOND:
        try:
            return "%d 秒" % int(value)
        except (TypeError, ValueError):
            return str(value)
    try:
        if english_name == "Service-Type":
            return "%s（%d）" % (SERVICE_TYPE_NAMES.get(int(value), "未知"), int(value))
        if english_name == "Termination-Action":
            return "%s（%d）" % (TERMINATION_ACTION_NAMES.get(int(value), "未知"), int(value))
    except (TypeError, ValueError):
        return str(value)
    return str(value)


def build_item(vendor_id, attribute_id, raw_value, template: str = "") -> Optional[dict]:
    """
    由属性编号与原始值生成一条授权属性记录。

    参数：
        vendor_id: 厂商编号
        attribute_id: 属性编号
        raw_value: 属性值（字符串或数字）
        template: 命中的字典模板名

    返回：
        授权属性字典；未收录的编号返回 None。
    """
    definition = classify(vendor_id, attribute_id)
    if definition is None:
        return None
    name, name_zh, type_name, category, unit, desc = definition
    return {
        "attribute_id": int(attribute_id),
        "vendor_id": int(vendor_id) if vendor_id else None,
        "template": template or ("Huawei" if vendor_id else "RFC2865"),
        "name": name,
        "name_zh": name_zh,
        "type": type_name,
        "category": category,
        "category_zh": category_text(category),
        "value": raw_value,
        "display": format_value(unit, raw_value, name),
        "unit": unit,
        "description": desc,
    }


def sort_items(items: List[dict]) -> List[dict]:
    """按分类顺序与属性编号排序。"""
    order = {name: index for index, name in enumerate(CATEGORY_ORDER)}
    return sorted(items, key=lambda item: (order.get(item["category"], 99),
                                           item["attribute_id"]))


def extract(packet) -> List[dict]:
    """
    从报文中提取授权属性（含厂商私有属性）。

    参数：
        packet: RadiusPacket 对象

    返回：
        授权属性列表（按分类顺序排序）。
    """
    result = []
    if packet is None:
        return result
    for attr in packet.attributes:
        template = ""
        if attr.matches:
            template = attr.matches[0].get("template", "")
        item = build_item(attr.vendor_id, attr.attr_id, attr.value, template)
        if item is not None:
            result.append(item)
    return sort_items(result)


def from_rows(rows: List[dict]) -> List[dict]:
    """
    由数据库属性行生成授权属性列表。

    参数：
        rows: radius_attributes 行，需含 attribute_id / vendor_id / value / radius_template

    返回：
        授权属性列表（按分类顺序排序）。
    """
    result = []
    for row in rows or []:
        item = build_item(row.get("vendor_id"), row.get("attribute_id"),
                          row.get("value"), row.get("radius_template") or "")
        if item is not None:
            result.append(item)
    return sort_items(result)


def group_items(items: List[dict]) -> List[dict]:
    """
    按分类分组，供详情页分区展示。

    返回：
        [{"category": "vlan", "category_zh": "隧道 / VLAN", "items": [...]}, ...]
    """
    groups = []
    for category in CATEGORY_ORDER:
        subset = [item for item in items if item["category"] == category]
        if subset:
            groups.append({
                "category": category,
                "category_zh": category_text(category),
                "items": subset,
            })
    return groups


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
    if attr_id in (27, 28, 85) or attr_id == ATTR_ACCT_INTERIM_INTERVAL:
        return "%d 秒" % number
    return ""


def has_authorization(packet) -> bool:
    """判断响应报文是否携带了授权属性。"""
    return len(extract(packet)) > 0
