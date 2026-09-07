# -*- coding: utf-8 -*-
"""
RADIUS 报文编解码模块。

职责：
    1. 把 (Code, Identifier, Authenticator, Attributes) 编码为完整 RADIUS 报文；
    2. 把收到的字节串解码为结构化报文对象。

报文结构（RFC 2865 第 3 节）：
    0      1      2      3      4
    +------+------+------+------+
    | Code |  ID  |   Length    |
    +------+------+------+------+
    |         Authenticator     |
    |           (16 字节)        |
    +---------------------------+
    |         Attributes        |
    +---------------------------+
"""

import struct
from typing import Optional

from . import attributes as attr_mod
from . import codes
from .authenticator import AUTHENTICATOR_LENGTH

# 报文头部长度：Code(1) + ID(1) + Length(2) + Authenticator(16)
PACKET_HEADER_LENGTH = 20
# RADIUS over UDP 报文最大长度（Length 字段为 2 字节）
MAX_PACKET_LENGTH = 4096
MIN_PACKET_LENGTH = PACKET_HEADER_LENGTH


class RadiusPacket:
    """
    RADIUS 报文对象。

    属性：
        code: 报文类型
        identifier: 报文标识
        authenticator: 16 字节认证器
        raw: 完整原始报文
        attributes: 已解析的属性对象列表
        parse_status: 解析状态（ok / partial / error）
        parse_error: 解析错误描述
    """

    __slots__ = ("code", "identifier", "authenticator", "raw", "attributes",
                 "parse_status", "parse_error")

    def __init__(
        self,
        code: int,
        identifier: int,
        authenticator: bytes,
        raw: bytes,
        attribute_list=None,
        parse_status: str = "ok",
        parse_error: str = "",
    ):
        self.code = code
        self.identifier = identifier
        self.authenticator = authenticator
        self.raw = raw
        self.attributes = attribute_list if attribute_list is not None else []
        self.parse_status = parse_status
        self.parse_error = parse_error

    @property
    def code_name(self) -> str:
        """报文类型名称。"""
        return codes.packet_code_name(self.code)

    @property
    def length(self) -> int:
        """报文长度。"""
        return len(self.raw)

    def find(self, attr_id: int, vendor_id: Optional[int] = None):
        """查找首个匹配的属性对象。"""
        for item in self.attributes:
            if item.attr_id == attr_id and item.vendor_id == vendor_id:
                return item
        return None

    def find_all(self, attr_id: int, vendor_id: Optional[int] = None) -> list:
        """查找全部匹配的属性对象。"""
        return [a for a in self.attributes if a.attr_id == attr_id and a.vendor_id == vendor_id]

    def to_dict(self) -> dict:
        """转换为可序列化字典。"""
        return {
            "code": self.code,
            "code_name": self.code_name,
            "identifier": self.identifier,
            "length": self.length,
            "authenticator": self.authenticator.hex(),
            "raw": self.raw.hex(),
            "parse_status": self.parse_status,
            "parse_error": self.parse_error,
            "attributes": [a.to_dict() for a in self.attributes],
        }


def encode_packet(code: int, identifier: int, authenticator: bytes, attribute_bytes: bytes) -> bytes:
    """
    编码完整 RADIUS 报文。

    参数：
        code: 报文类型
        identifier: 报文标识
        authenticator: 16 字节认证器
        attribute_bytes: 属性区字节串

    返回：
        完整报文字节串。
    """
    if len(authenticator) != AUTHENTICATOR_LENGTH:
        raise ValueError("认证器长度必须是 %d 字节" % AUTHENTICATOR_LENGTH)
    length = PACKET_HEADER_LENGTH + len(attribute_bytes)
    if length > MAX_PACKET_LENGTH:
        raise ValueError("报文长度 %d 超过上限 %d" % (length, MAX_PACKET_LENGTH))
    header = struct.pack(">BBH", code, identifier & 0xFF, length)
    return header + authenticator + attribute_bytes


def decode_packet(data: bytes) -> RadiusPacket:
    """
    解码 RADIUS 报文。

    参数：
        data: 收到的原始字节串

    返回：
        RadiusPacket 对象。

    说明：
        报文长度不足、长度字段与实际不符时标记为 partial 或 error，
        仍然返回对象，保证上层可以查看已解析部分。
    """
    if len(data) < PACKET_HEADER_LENGTH:
        return RadiusPacket(
            code=0,
            identifier=0,
            authenticator=b"",
            raw=data,
            parse_status="error",
            parse_error="报文长度不足 %d 字节，实际 %d 字节" % (PACKET_HEADER_LENGTH, len(data)),
        )
    code = data[0]
    identifier = data[1]
    length = struct.unpack(">H", data[2:4])[0]
    authenticator = data[4:PACKET_HEADER_LENGTH]
    payload = data[PACKET_HEADER_LENGTH:]
    parse_status = "ok"
    parse_error = ""
    if length < PACKET_HEADER_LENGTH:
        parse_status = "error"
        parse_error = "Length 字段非法：%d" % length
    elif length > len(data):
        parse_status = "partial"
        parse_error = "Length 字段 %d 大于实际收到 %d 字节" % (length, len(data))
        payload = data[PACKET_HEADER_LENGTH:]
    elif length < len(data):
        # 实际收到的数据多于 Length 字段声明，按声明截断
        payload = data[PACKET_HEADER_LENGTH:length]
    parsed = attr_mod.decode_attributes(payload)
    return RadiusPacket(
        code=code,
        identifier=identifier,
        authenticator=authenticator,
        raw=data,
        attribute_list=parsed,
        parse_status=parse_status,
        parse_error=parse_error,
    )
