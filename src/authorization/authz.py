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


# ---------------- 中文说明（说明列来源） ----------------
# 标准属性（vendor_id 为空）的中文释义：编号 -> 说明。
# 覆盖 RFC2865 / RFC2866 / RFC2869 / RFC2868 / RFC3162 等常见属性，
# 说明侧重「这个属性在排错时代表什么」，未收录的编号返回空串（前端显示 −）。
STANDARD_DESCRIPTIONS: Dict[int, str] = {
    1: "用户名，标识接入用户的账号",
    2: "用户密码，加密后传输",
    3: "CHAP 密码，Challenge-Handshake 认证凭证",
    4: "NAS（接入服务器）的 IP 地址",
    5: "NAS 上的物理/逻辑端口号",
    6: "服务类型，标识请求的服务种类（如 Framed、Login）",
    7: "帧协议，如 PPP",
    8: "分配给用户的 IP 地址",
    9: "用户 IP 地址的子网掩码",
    10: "路由协议类型",
    11: "过滤规则标识（ACL 名称），用于下发访问控制",
    12: "帧最大传输单元 MTU",
    13: "回拨号码",
    14: "回拨标识",
    15: "帧压缩方式",
    16: "登录主机 IP",
    17: "登录服务类型",
    18: "登录 TCP 端口",
    19: "帧 AppleTalk 网络号",
    20: "帧 AppleTalk 链路",
    21: "帧 AppleTalk 区域",
    22: "代理状态，经过代理时原样回传",
    23: "NAS 标识名称",
    24: "状态属性，用于多轮认证（如 Challenge）流程",
    25: "分类标识，由服务器下发、客户端需原样回传",
    26: "厂商私有属性（VSA）容器",
    27: "会话超时时间，单位秒，到期强制断开",
    28: "空闲超时时间，单位秒，无流量则断开",
    29: "终止动作，会话结束后是否重新发起认证",
    30: "被叫站点标识，通常包含 SSID 或 NAS 端口信息",
    31: "主叫站点标识，通常包含用户终端 MAC",
    32: "NAS 标识名称（字符串形式）",
    33: "代理状态，原样回传",
    38: "计费状态类型（Start / Stop / Interim-Update）",
    39: "计费报文在途延迟，单位秒",
    40: "计费入方向字节数",
    41: "计费出方向字节数",
    42: "计费会话 ID",
    43: "计费认证方式",
    44: "计费会话时长，单位秒",
    45: "计费入方向包数",
    46: "计费出方向包数",
    47: "会话终止原因",
    48: "多会话 ID",
    49: "链路计数",
    50: "分类标识（部分实现用 50 而非 25）",
    55: "事件时间戳",
    60: "CHAP 挑战值（CHAP-Challenge）",
    61: "NAS 端口类型，如 Ethernet / Wireless-802.11 / Virtual",
    64: "隧道类型，如 L2TP / VLAN",
    65: "隧道介质类型，通常为 IEEE-802",
    66: "隧道客户端端点，通常为 VLAN 名称/ID",
    67: "隧道服务端端点",
    68: "隧道口令（Tunnel-Password）",
    69: "隧道私有组 ID，用于标识隧道所属组",
    70: "NAS 端口 ID（字符串，常含插槽/端口）",
    71: "NAS 端口类型（字符串）",
    72: "隧道分配 ID（Tunnel-Assignment-ID）",
    73: "隧道偏好（Tunnel-Preference）",
    75: "隧道客户端认证 ID",
    76: "隧道服务端认证 ID",
    77: "隧道客户端认证密码",
    78: "隧道服务端认证密码",
    79: "EAP 消息，承载 802.1X/EAP 认证报文",
    80: "消息认证码，保护报文完整性",
    81: "隧道私有组标识（常下发 VLAN 编号或 VLAN 名称）",
    82: "隧道媒体组 ID",
    83: "隧道类型（Tagged / Untagged）",
    85: "计费间隔，单位秒，周期性发送 Interim-Update",
    86: "计费可容忍延迟",
    87: "NAS 端口 ID（同 70，部分实现用 87）",
    88: "帧地址池名称，用于分配 IP",
    89: "隧道客户端认证 ID（字符串）",
    90: "隧道服务端认证 ID（字符串）",
    95: "NAS 的 IPv6 地址",
    96: "帧 IPv6 地址",
    97: "帧 IPv6 前缀长度",
    98: "帧 IPv6 路由前缀",
    99: "帧 IPv6 路由，如 RIP / OSPF",
    100: "帧 IPv6 池名称",
    101: "计费输入千兆字（Gigawords，高位进位）",
    102: "计费输出千兆字（Gigawords，高位进位）",
    123: "DNS 服务器地址（RFC6911）",
    124: "DHCP 服务器地址（RFC6911）",
    126: "错误原因（Error-Cause）",
    127: "Delegated-IPv6-Prefix，委派的 IPv6 前缀",
}

# 厂商私有属性中文释义：键 (vendor_id, attribute_id, name) -> 说明。
# 覆盖 H3C / HP / Juniper / Mikrotik / Aruba / WISPr 六家内置字典；
# 说明为人工整理的中文释义，未收录的属性返回空串（前端显示 −）。
VENDOR_DESCRIPTIONS: Dict[Tuple[int, int, str], str] = {
    # ---------------- H3C (vendor_id = 25506) ----------------
    (25506, 1, "H3C-Input-Peak-Rate"): "用户入方向（上传）峰值速率，单位 bit/s",
    (25506, 2, "H3C-Input-Average-Rate"): "用户入方向平均速率，单位 bit/s",
    (25506, 3, "H3C-Input-Basic-Rate"): "用户入方向基础（保底）速率，单位 bit/s",
    (25506, 15, "H3C-Remanent-Volume"): "用户剩余可用流量配额，单位字节",
    (25506, 20, "H3C-Command"): "下发到设备的命令行（如 1=执行），用于权限控制",
    (25506, 24, "H3C-Control-Identifier"): "控制标识，标识本次控制操作的类型",
    (25506, 25, "H3C-Result-Code"): "操作结果码，标识请求处理结果",
    (25506, 26, "H3C-Connect_Id"): "连接标识，唯一标识一条用户连接",
    (25506, 28, "H3C-Ftp-Directory"): "授权用户的 FTP 主目录路径",
    (25506, 29, "H3C-Exec-Privilege"): "用户命令行执行特权级别（数值越大权限越高）",
    (25506, 59, "H3C-NAS-Startup-Timestamp"): "NAS 设备启动时间戳",
    (25506, 60, "H3C-Ip-Host-Addr"): "分配给用户的主机 IP 地址",
    (25506, 61, "H3C-User-Notify"): "向用户下发的通知信息",
    (25506, 62, "H3C-User-HeartBeat"): "用户心跳报文内容，用于保持连接",
    (25506, 140, "H3C-User-Group"): "用户所属用户组名称",
    (25506, 141, "H3C-Security-Level"): "用户安全级别",
    (25506, 201, "H3C-Input-Interval-Octets"): "统计周期内入方向字节数",
    (25506, 202, "H3C-Output-Interval-Octets"): "统计周期内出方向字节数",
    (25506, 203, "H3C-Input-Interval-Packets"): "统计周期内入方向包数",
    (25506, 204, "H3C-Output-Interval-Packets"): "统计周期内出方向包数",
    (25506, 205, "H3C-Input-Interval-Gigawords"): "入方向字节数高位计数（吉字节进位）",
    (25506, 206, "H3C-Output-Interval-Gigawords"): "出方向字节数高位计数（吉字节进位）",
    (25506, 207, "H3C-Backup-NAS-IP"): "备份 NAS 的 IP 地址",
    (25506, 255, "H3C-Product-ID"): "设备产品标识 ID",

    # ---------------- HP (vendor_id = 11) ----------------
    (11, 1, "HP-Privilege-Level"): "用户管理特权级别（数值越大权限越高）",
    (11, 2, "HP-Command-String"): "授权可执行的命令行字符串",
    (11, 3, "HP-Command-Exception"): "命令行例外标识（允许/拒绝特定命令）",
    (11, 10, "HP-Port-Client-Limit-Dot1x"): "端口 802.1X 认证的最大客户端数",
    (11, 11, "HP-Port-Client-Limit-MA"): "端口 MAC 认证的最大客户端数",
    (11, 12, "HP-Port-Client-Limit-WA"): "端口 Web 认证的最大客户端数",
    (11, 13, "HP-Port-Auth-Mode-Dot1x"): "端口 802.1X 认证模式",
    (11, 26, "HP-Management-Protocol"): "允许的管理协议类型",
    (11, 40, "HP-Cos"): "服务等级（Class of Service），用于报文优先级标记",
    (11, 40, "HP-Port-Priority-Regeneration-Table"):
        "端口优先级再生表，重写入方向报文的优先级",
    (11, 46, "HP-Bandwidth-Max-Ingress"): "端口/用户最大入方向带宽，单位 bit/s",
    (11, 48, "HP-Bandwidth-Max-Egress"): "端口/用户最大出方向带宽，单位 bit/s",
    (11, 61, "HP-Ip-Filter-Raw"): "IP 过滤原始规则数据",
    (11, 61, "HP-Nas-Filter-Rule"): "NAS 过滤规则（IP 访问策略），格式同 RFC 标准",
    (11, 63, "HP-Nas-Rules-IPv6"): "IPv6 的 NAS 过滤规则",
    (11, 64, "HP-Egress-VLANID"): "下发到端口的出方向 VLAN ID（VLAN 授权）",
    (11, 65, "HP-Egress-VLAN-Name"): "下发到端口的出方向 VLAN 名称",
    (11, 255, "HP-Capability-Advert"): "设备能力通告（厂商私有能力位）",

    # ---------------- Juniper (vendor_id = 2636) ----------------
    (2636, 1, "Juniper-Local-User-Name"): "下发的本地用户名，用于设备本地登录授权",
    (2636, 2, "Juniper-Allow-Commands"): "允许执行的命令列表（支持正则/通配）",
    (2636, 3, "Juniper-Deny-Commands"): "拒绝执行的命令列表",
    (2636, 4, "Juniper-Allow-Configuration"): "允许修改的配置语句列表",
    (2636, 5, "Juniper-Deny-Configuration"): "拒绝修改的配置语句列表",
    (2636, 8, "Juniper-Interactive-Command"): "允许的交互式命令",
    (2636, 9, "Juniper-Configuration-Change"): "配置变更记录/标识",
    (2636, 10, "Juniper-User-Permissions"): "用户权限集（登录类权限）",
    (2636, 11, "Juniper-Junosspace-Profile"): "Junos Space 管理平台下发的配置文件名",
    (2636, 21, "Juniper-CTP-Group"): "CTP 组标识",
    (2636, 22, "Juniper-CTPView-APP-Group"): "CTPView 应用组标识",
    (2636, 23, "Juniper-CTPView-OS-Group"): "CTPView 操作系统组标识",
    (2636, 31, "Juniper-Primary-Dns"): "主 DNS 服务器地址",
    (2636, 32, "Juniper-Primary-Wins"): "主 WINS 服务器地址",
    (2636, 33, "Juniper-Secondary-Dns"): "备用 DNS 服务器地址",
    (2636, 34, "Juniper-Secondary-Wins"): "备用 WINS 服务器地址",
    (2636, 35, "Juniper-Interface-id"): "接口标识",
    (2636, 36, "Juniper-Ip-Pool-Name"): "分配的 IP 地址池名称",
    (2636, 37, "Juniper-Keep-Alive"): "连接保活时间间隔，单位秒",
    (2636, 38, "Juniper-CoS-Traffic-Control-Profile"): "CoS 流量控制配置文件名",
    (2636, 39, "Juniper-CoS-Parameter"): "CoS 参数",
    (2636, 40, "Juniper-encapsulation-overhead"): "封装开销字节数（用于速率计算）",
    (2636, 41, "Juniper-cell-overhead"): "信元开销字节数（ATM 等场景）",
    (2636, 42, "Juniper-tx-connect-speed"): "发送连接速率，单位 bit/s",
    (2636, 43, "Juniper-rx-connect-speed"): "接收连接速率，单位 bit/s",
    (2636, 44, "Juniper-Firewall-filter-name"): "防火墙过滤策略名称",
    (2636, 45, "Juniper-Policer-Parameter"): "限速器（Policer）参数",
    (2636, 46, "Juniper-Local-Group-Name"): "本地组名称",
    (2636, 47, "Juniper-Local-Interface"): "本地接口名称",
    (2636, 48, "Juniper-Switching-Filter"): "交换过滤策略名称",
    (2636, 49, "Juniper-VoIP-Vlan"): "语音 VLAN 标识/名称，用于 IP 电话接入",

    # ---------------- Mikrotik (vendor_id = 14988) ----------------
    (14988, 1, "Mikrotik-Recv-Limit"): "接收方向流量上限，单位字节",
    (14988, 2, "Mikrotik-Xmit-Limit"): "发送方向流量上限，单位字节",
    (14988, 3, "Mikrotik-Group"): "用户所属组",
    (14988, 4, "Mikrotik-Wireless-Forward"): "是否允许无线转发（0/1）",
    (14988, 5, "Mikrotik-Wireless-Skip-Dot1x"): "是否跳过 802.1X 无线认证（0/1）",
    (14988, 6, "Mikrotik-Wireless-Enc-Algo"): "无线加密算法编号",
    (14988, 7, "Mikrotik-Wireless-Enc-Key"): "无线加密密钥",
    (14988, 8, "Mikrotik-Rate-Limit"): "速率限制字符串，如 1M/2M（上/下行）",
    (14988, 9, "Mikrotik-Realm"): "认证域（Realm）",
    (14988, 10, "Mikrotik-Host-IP"): "分配给用户的主机 IP 地址",
    (14988, 11, "Mikrotik-Mark-Id"): "防火墙标记 ID",
    (14988, 12, "Mikrotik-Advertise-URL"): "通告页面 URL",
    (14988, 13, "Mikrotik-Advertise-Interval"): "通告间隔，单位秒",
    (14988, 14, "Mikrotik-Recv-Limit-Gigawords"): "接收限制高位计数（吉字节进位）",
    (14988, 15, "Mikrotik-Xmit-Limit-Gigawords"): "发送限制高位计数（吉字节进位）",
    (14988, 16, "Mikrotik-Wireless-PSK"): "无线 PSK 预共享密钥",
    (14988, 17, "Mikrotik-Total-Limit"): "收发总流量上限，单位字节",
    (14988, 18, "Mikrotik-Total-Limit-Gigawords"): "总流量限制高位计数（吉字节进位）",
    (14988, 19, "Mikrotik-Address-List"): "地址列表名，用于防火墙归类",
    (14988, 20, "Mikrotik-Wireless-MPKey"): "无线主密钥",
    (14988, 21, "Mikrotik-Wireless-Comment"): "无线备注信息",
    (14988, 22, "Mikrotik-Delegated-IPv6-Pool"): "委派的 IPv6 地址池名称",

    # ---------------- Aruba (vendor_id = 14823) ----------------
    (14823, 1, "Aruba-User-Role"): "用户角色（Role），决定访问控制策略",
    (14823, 2, "Aruba-User-Vlan"): "授权给用户的可变 VLAN ID",
    (14823, 3, "Aruba-Priv-Admin-User"): "是否为特权管理员用户（0/1）",
    (14823, 4, "Aruba-Admin-Role"): "管理员角色名称",
    (14823, 5, "Aruba-Essid-Name"): "ESSID（无线 SSID）名称",
    (14823, 6, "Aruba-Location-Id"): "位置标识（AP 物理位置）",
    (14823, 7, "Aruba-Port-Identifier"): "端口标识",
    (14823, 8, "Aruba-MMS-User-Template"): "MMS 用户模板",
    (14823, 9, "Aruba-Named-User-Vlan"): "按名称指定的用户 VLAN",
    (14823, 10, "Aruba-AP-Group"): "AP 组名称",
    (14823, 11, "Aruba-Framed-IPv6-Address"): "下发的 IPv6 帧地址",
    (14823, 12, "Aruba-Device-Type"): "设备类型标识",
    (14823, 14, "Aruba-No-DHCP-Fingerprint"): "是否禁用 DHCP 指纹（0/1）",
    (14823, 15, "Aruba-Mdps-Device-Udid"): "MDM/MDPS 设备 UDID",
    (14823, 16, "Aruba-Mdps-Device-Imei"): "设备 IMEI",
    (14823, 17, "Aruba-Mdps-Device-Iccid"): "设备 ICCID（SIM 卡）",
    (14823, 18, "Aruba-Mdps-Max-Devices"): "最大允许注册设备数",
    (14823, 19, "Aruba-Mdps-Device-Name"): "设备名称",
    (14823, 20, "Aruba-Mdps-Device-Product"): "设备产品型号",
    (14823, 21, "Aruba-Mdps-Device-Version"): "设备系统版本",
    (14823, 22, "Aruba-Mdps-Device-Serial"): "设备序列号",
    (14823, 23, "Aruba-CPPM-Role"): "ClearPass 下发的角色",
    (14823, 24, "Aruba-AirGroup-User-Name"): "AirGroup 用户名",
    (14823, 25, "Aruba-AirGroup-Shared-User"): "AirGroup 共享用户",
    (14823, 26, "Aruba-AirGroup-Shared-Role"): "AirGroup 共享角色",
    (14823, 27, "Aruba-AirGroup-Device-Type"): "AirGroup 设备类型",
    (14823, 28, "Aruba-Auth-Survivability"): "认证生存性（断连后本地放行）标识",
    (14823, 29, "Aruba-AS-User-Name"): "AS（应用服务）用户名",
    (14823, 30, "Aruba-AS-Credential-Hash"): "AS 凭据哈希",
    (14823, 31, "Aruba-WorkSpace-App-Name"): "Workspace 应用名称",
    (14823, 32, "Aruba-Mdps-Provisioning-Settings"): "MDPS 供应设置",
    (14823, 33, "Aruba-Mdps-Device-Profile"): "MDPS 设备配置文件",
    (14823, 34, "Aruba-AP-IP-Address"): "AP 的 IP 地址",

    # ---------------- WISPr (vendor_id = 14122) ----------------
    (14122, 1, "WISPr-Location-ID"): "热点位置标识（运营商热点 ID）",
    (14122, 2, "WISPr-Location-Name"): "热点位置名称",
    (14122, 3, "WISPr-Logoff-URL"): "用户登出页面 URL",
    (14122, 4, "WISPr-Redirection-URL"): "登录后重定向的目标 URL",
    (14122, 5, "WISPr-Bandwidth-Min-Up"): "最小上行带宽保障，单位 bit/s",
    (14122, 6, "WISPr-Bandwidth-Min-Down"): "最小下行带宽保障，单位 bit/s",
    (14122, 7, "WISPr-Bandwidth-Max-Up"): "最大上行带宽限制，单位 bit/s",
    (14122, 8, "WISPr-Bandwidth-Max-Down"): "最大下行带宽限制，单位 bit/s",
    (14122, 9, "WISPr-Session-Terminate-Time"): "会话强制终止时间",
    (14122, 10, "WISPr-Session-Terminate-End-Of-Day"): "会话在日终终止的时间",
    (14122, 11, "WISPr-Billing-Class-Of-Service"): "计费服务等级（CoS）标识",
}


def describe_attribute(vendor_id, attribute_id, name: str = "") -> str:
    """
    返回属性的中文说明（说明列数据源）。

    优先级：
        1. 标准属性：STANDARD_DESCRIPTIONS；
        2. 华为私有属性（vendor_id=2011）：VENDOR_ATTRIBUTES 的第 6 元素；
        3. 六家厂商私有属性：VENDOR_DESCRIPTIONS（按 vendor_id+编号+英文名 精确匹配）；
        4. 均无则返回空串，前端显示为 −。

    参数：
        vendor_id: 厂商编号；标准属性传 None / 0 / 空
        attribute_id: 属性编号
        name: 属性英文名（用于区分同一厂商编号下的不同属性，如 HP id=40）
    """
    if not vendor_id:
        return STANDARD_DESCRIPTIONS.get(int(attribute_id), "")
    vendor_id = int(vendor_id)
    attribute_id = int(attribute_id)
    huawei = VENDOR_ATTRIBUTES.get((vendor_id, attribute_id))
    if huawei is not None:
        return huawei[5]
    exact = VENDOR_DESCRIPTIONS.get((vendor_id, attribute_id, name or ""))
    if exact is not None:
        return exact
    # 退化匹配：未提供 name 时仍尝试按编号匹配（仅当该编号唯一）。
    for key, value in VENDOR_DESCRIPTIONS.items():
        if key[0] == vendor_id and key[1] == attribute_id:
            return value
    return ""


def has_authorization(packet) -> bool:
    """判断响应报文是否携带了授权属性。"""
    return len(extract(packet)) > 0
