# -*- coding: utf-8 -*-
"""
RADIUS 常量与属性编解码模块。

职责：
    1. 定义 RADIUS 报文类型常量；
    2. 定义 RADIUS 属性的数据类型编码与解码规则。

参考：
    RFC 2865  Remote Authentication Dial In User Service
    RFC 2866  RADIUS Accounting
    RFC 3162  RADIUS and IPv6
    RFC 6929  RADIUS Protocol Extensions
"""

import ipaddress
import struct

# ---------------- RADIUS 报文类型 ----------------
ACCESS_REQUEST = 1
ACCESS_ACCEPT = 2
ACCESS_REJECT = 3
ACCOUNTING_REQUEST = 4
ACCOUNTING_RESPONSE = 5
ACCESS_CHALLENGE = 11
STATUS_SERVER = 12
STATUS_CLIENT = 13
DISCONNECT_REQUEST = 40
DISCONNECT_ACK = 41
DISCONNECT_NAK = 42
COA_REQUEST = 43
COA_ACK = 44
COA_NAK = 45

PACKET_CODE_NAMES = {
    ACCESS_REQUEST: "Access-Request",
    ACCESS_ACCEPT: "Access-Accept",
    ACCESS_REJECT: "Access-Reject",
    ACCOUNTING_REQUEST: "Accounting-Request",
    ACCOUNTING_RESPONSE: "Accounting-Response",
    ACCESS_CHALLENGE: "Access-Challenge",
    STATUS_SERVER: "Status-Server",
    STATUS_CLIENT: "Status-Client",
    DISCONNECT_REQUEST: "Disconnect-Request",
    DISCONNECT_ACK: "Disconnect-ACK",
    DISCONNECT_NAK: "Disconnect-NAK",
    COA_REQUEST: "CoA-Request",
    COA_ACK: "CoA-ACK",
    COA_NAK: "CoA-NAK",
}

# ---------------- 计费状态类型（RFC 2866） ----------------
ACCT_STATUS_START = 1
ACCT_STATUS_STOP = 2
ACCT_STATUS_INTERIM_UPDATE = 3
ACCT_STATUS_ACCOUNTING_ON = 7
ACCT_STATUS_ACCOUNTING_OFF = 8

# ---------------- 特殊属性编号 ----------------
ATTR_USER_NAME = 1
ATTR_USER_PASSWORD = 2
ATTR_CHAP_PASSWORD = 3
ATTR_NAS_IP_ADDRESS = 4
ATTR_NAS_PORT = 5
ATTR_SERVICE_TYPE = 6
ATTR_VENDOR_SPECIFIC = 26
ATTR_CALLED_STATION_ID = 30
ATTR_CALLING_STATION_ID = 31
ATTR_NAS_IDENTIFIER = 32
ATTR_PROXY_STATE = 33
ATTR_ACCT_STATUS_TYPE = 40
ATTR_ACCT_SESSION_ID = 44
ATTR_ACCT_TERMINATE_CAUSE = 49
ATTR_EAP_MESSAGE = 79
ATTR_MESSAGE_AUTHENTICATOR = 80
ATTR_ACCT_INTERIM_INTERVAL = 85
ATTR_NAS_PORT_ID = 87
ATTR_CHARGEABLE_USER_IDENTITY = 89

# ---------------- 属性数据类型 ----------------
TYPE_STRING = "string"
TYPE_OCTETS = "octets"
TYPE_INTEGER = "integer"
TYPE_SHORT = "short"
TYPE_BYTE = "byte"
TYPE_IPADDR = "ipaddr"
TYPE_DATE = "date"
TYPE_IPV6ADDR = "ipv6addr"
TYPE_IPV6PREFIX = "ipv6prefix"
TYPE_IFID = "ifid"
TYPE_SIGNED = "signed"
TYPE_TLV = "tlv"
TYPE_UNKNOWN = "unknown"

# 允许在 Dictionary 中声明的类型
SUPPORTED_TYPES = (
    TYPE_STRING,
    TYPE_OCTETS,
    TYPE_INTEGER,
    TYPE_SHORT,
    TYPE_BYTE,
    TYPE_IPADDR,
    TYPE_DATE,
    TYPE_IPV6ADDR,
    TYPE_IPV6PREFIX,
    TYPE_IFID,
    TYPE_SIGNED,
    TYPE_TLV,
)


def encode_value(type_name: str, value) -> bytes:
    """
    按属性类型把 Python 值编码为 RADIUS 属性值字节串。

    参数：
        type_name: 属性类型名称
        value: 待编码值（字符串、整数或字节串）

    返回：
        编码后的字节串。
    """
    if isinstance(value, bytes):
        return value
    text = "" if value is None else str(value)
    if type_name == TYPE_INTEGER or type_name == TYPE_DATE:
        return struct.pack(">I", int(value))
    if type_name == TYPE_SIGNED:
        return struct.pack(">i", int(value))
    if type_name == TYPE_SHORT:
        return struct.pack(">H", int(value))
    if type_name == TYPE_BYTE:
        return bytes([int(value) & 0xFF])
    if type_name == TYPE_IPADDR:
        return ipaddress.IPv4Address(text).packed
    if type_name == TYPE_IPV6ADDR:
        return ipaddress.IPv6Address(text).packed
    if type_name == TYPE_IFID:
        return int(text.replace(":", ""), 16).to_bytes(8, "big")
    if type_name == TYPE_IPV6PREFIX:
        # 格式：1 字节保留 + 1 字节前缀长度 + 16 字节地址
        if "/" in text:
            addr_text, plen_text = text.split("/", 1)
            plen = int(plen_text)
        else:
            addr_text, plen = text, 128
        return bytes([0, plen]) + ipaddress.IPv6Address(addr_text).packed
    # string / octets / tlv / unknown 统一按文本编码
    return text.encode("utf-8")


def decode_value(type_name: str, raw: bytes):
    """
    按属性类型把 RADIUS 属性值解码为可展示的 Python 值。

    解码失败时返回十六进制字符串，保证解析不会中断。
    """
    try:
        if type_name == TYPE_INTEGER:
            return struct.unpack(">I", raw)[0]
        if type_name == TYPE_SIGNED:
            return struct.unpack(">i", raw)[0]
        if type_name == TYPE_SHORT:
            return struct.unpack(">H", raw)[0]
        if type_name == TYPE_BYTE:
            return raw[0]
        if type_name == TYPE_IPADDR:
            return str(ipaddress.IPv4Address(raw))
        if type_name == TYPE_IPV6ADDR:
            return str(ipaddress.IPv6Address(raw))
        if type_name == TYPE_IFID:
            return raw.hex(":")
        if type_name == TYPE_IPV6PREFIX:
            plen = raw[1] if len(raw) > 1 else 0
            addr = ipaddress.IPv6Address(raw[2:18])
            return "%s/%d" % (addr, plen)
        if type_name == TYPE_DATE:
            return struct.unpack(">I", raw)[0]
        if type_name == TYPE_OCTETS:
            return raw.hex()
    except Exception:
        return raw.hex()
    # string / tlv / unknown 优先按 UTF-8 解码
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.hex()
    # 控制字符过多时按十六进制展示，避免污染页面
    if sum(1 for ch in decoded if ord(ch) < 32 and ch not in "\r\n\t") > 0:
        return raw.hex()
    return decoded


def packet_code_name(code: int) -> str:
    """返回报文类型名称，未知类型返回 Unknown(code)。"""
    return PACKET_CODE_NAMES.get(code, "Unknown(%d)" % code)
