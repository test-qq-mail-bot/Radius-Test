# -*- coding: utf-8 -*-
"""
RADIUS 属性编解码模块。

职责：
    1. 把属性列表编码为 RADIUS 报文属性区字节串；
    2. 把属性区字节串解析为结构化的属性对象列表；
    3. 处理厂商自定义属性 VSA（属性 26）与扩展属性（RFC 6929）。

设计原则（项目书 17.2）：
    本模块只做「按字节结构解析」，不做模板匹配。
    模板匹配由 parser 模块在解析完成之后统一进行。
"""

import struct
from typing import List, Optional

from . import codes
from ..common.errors import RadiusError

# 扩展属性类型（RFC 6929）
EXTENDED_TYPE_1 = 241
EXTENDED_TYPE_2 = 242

# 单个属性值的最大长度（RADIUS 属性 Length 字段为 1 字节）
MAX_ATTRIBUTE_VALUE_LENGTH = 253


class RadiusAttribute:
    """
    RADIUS 属性对象。

    属性：
        attr_id: 属性编号；VSA 时为厂商子类型编号
        vendor_id: 厂商编号，标准属性为 None
        raw: 属性原始值字节串
        attr_type: 属性数据类型（由 Dictionary 匹配后填充）
        name: 英文属性名（由 Dictionary 匹配后填充）
        name_zh: 中文属性名（由 Dictionary 匹配后填充）
        value: 解码后的值（由 Dictionary 匹配后填充）
        matches: 模板匹配结果列表，一个属性可能匹配多个模板
    """

    __slots__ = ("attr_id", "vendor_id", "raw", "attr_type", "name", "name_zh", "value", "matches")

    def __init__(self, attr_id: int, vendor_id: Optional[int], raw: bytes):
        self.attr_id = attr_id
        self.vendor_id = vendor_id
        self.raw = raw
        self.attr_type = codes.TYPE_UNKNOWN
        self.name = "Unknown"
        self.name_zh = "未知属性"
        self.value = raw.hex()
        self.matches: List[dict] = []

    @property
    def is_vsa(self) -> bool:
        """是否为厂商自定义属性。"""
        return self.vendor_id is not None

    def to_dict(self) -> dict:
        """转换为可序列化的字典，供 API 与前端使用。"""
        return {
            "attribute_id": self.attr_id,
            "vendor_id": self.vendor_id,
            "radius_template": self.matches[0]["template"] if self.matches else "Unknown",
            "name": self.name,
            "name_zh": self.name_zh,
            "type": self.attr_type,
            "value": _safe_text(self.value),
            "raw": self.raw.hex(),
            "matches": self.matches,
        }


def _safe_text(value) -> str:
    """把任意值转换为可安全展示的字符串。"""
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def encode_vsa(vendor_id: int, sub_attributes: List[tuple]) -> bytes:
    """
    编码厂商自定义属性 VSA（属性 26）。

    参数：
        vendor_id: 厂商编号
        sub_attributes: [(子类型编号, 值字节串), ...]

    返回：
        属性 26 的完整值（含 4 字节 Vendor-ID 与子 TLV）。
    """
    body = struct.pack(">I", vendor_id)
    for sub_id, sub_value in sub_attributes:
        if len(sub_value) > MAX_ATTRIBUTE_VALUE_LENGTH - 2:
            raise RadiusError(
                "VSA 子属性值过长",
                "vendor_id=%s；sub_id=%s；长度=%d" % (vendor_id, sub_id, len(sub_value)),
            )
        body += bytes([sub_id & 0xFF, len(sub_value) + 2]) + sub_value
    if len(body) > MAX_ATTRIBUTE_VALUE_LENGTH:
        raise RadiusError("VSA 属性总长度超限", "vendor_id=%s；长度=%d" % (vendor_id, len(body)))
    return body


def encode_attribute(attr_id: int, value: bytes) -> bytes:
    """
    编码单个标准属性。

    参数：
        attr_id: 属性编号
        value: 属性原始值字节串

    返回：
        完整 TLV 字节串。
    """
    if len(value) > MAX_ATTRIBUTE_VALUE_LENGTH:
        raise RadiusError(
            "属性值长度超限",
            "attr_id=%s；长度=%d；上限=%d" % (attr_id, len(value), MAX_ATTRIBUTE_VALUE_LENGTH),
        )
    return bytes([attr_id & 0xFF, len(value) + 2]) + value


def encode_attributes(attributes: List[tuple]) -> bytes:
    """
    编码属性列表。

    参数：
        attributes: [(属性编号, 值字节串), ...]，VSA 的值应为 encode_vsa 的结果

    返回：
        属性区字节串。
    """
    out = bytearray()
    for attr_id, value in attributes:
        out += encode_attribute(attr_id, value)
    return bytes(out)


def decode_attributes(data: bytes) -> List[RadiusAttribute]:
    """
    解析属性区字节串。

    参数：
        data: 属性区字节串

    返回：
        RadiusAttribute 对象列表。

    说明：
        遇到长度非法或截断的数据时停止解析，已解析出的属性照常返回，
        保证部分损坏的报文仍可查看。
    """
    attributes: List[RadiusAttribute] = []
    offset = 0
    total = len(data)
    while offset + 2 <= total:
        attr_id = data[offset]
        length = data[offset + 1]
        if length < 2 or offset + length > total:
            break
        value = data[offset + 2:offset + length]
        offset += length
        if attr_id == codes.ATTR_VENDOR_SPECIFIC:
            attributes.extend(_decode_vsa(value))
        elif attr_id in (EXTENDED_TYPE_1, EXTENDED_TYPE_2):
            attributes.extend(_decode_extended(attr_id, value))
        else:
            attributes.append(RadiusAttribute(attr_id, None, value))
    return attributes


def _decode_vsa(value: bytes) -> List[RadiusAttribute]:
    """
    解析厂商自定义属性 VSA。

    结构：4 字节 Vendor-ID + N 个 (1 字节子类型 + 1 字节长度 + 值)。
    """
    result: List[RadiusAttribute] = []
    if len(value) < 4:
        return result
    vendor_id = struct.unpack(">I", value[:4])[0]
    offset = 4
    total = len(value)
    while offset + 2 <= total:
        sub_id = value[offset]
        sub_len = value[offset + 1]
        if sub_len < 2 or offset + sub_len > total:
            break
        sub_value = value[offset + 2:offset + sub_len]
        offset += sub_len
        result.append(RadiusAttribute(sub_id, vendor_id, sub_value))
    return result


def _decode_extended(ext_type: int, value: bytes) -> List[RadiusAttribute]:
    """
    解析 RFC 6929 扩展属性。

    扩展属性把属性编号空间从 256 扩展到 65536，
    本项目只做基础解析，扩展编号映射为 256 * 256 + 原始编号。
    """
    result: List[RadiusAttribute] = []
    if len(value) < 2:
        return result
    ext_attr_id = value[0]
    # 扩展类型 2 使用 2 字节属性编号
    if ext_type == EXTENDED_TYPE_2 and len(value) >= 3:
        ext_attr_id = struct.unpack(">H", value[:2])[0]
        payload = value[2:]
    else:
        payload = value[1:]
    result.append(RadiusAttribute(0x10000 + ext_attr_id, None, payload))
    return result


def split_eap_messages(attributes: List[RadiusAttribute]) -> bytes:
    """
    重组 EAP-Message 分片（项目书 11.1）。

    参数：
        attributes: 已解析的属性列表

    返回：
        拼接后的完整 EAP 报文字节串；无 EAP-Message 时返回空字节串。
    """
    chunks = [a.raw for a in attributes if a.attr_id == codes.ATTR_EAP_MESSAGE and not a.is_vsa]
    return b"".join(chunks)


def split_eap_to_attributes(eap_data: bytes, chunk_size: int = 253) -> List[bytes]:
    """
    把 EAP 报文拆分为多个 EAP-Message 属性。

    参数：
        eap_data: 完整 EAP 报文字节串
        chunk_size: 单个属性最大长度，默认 253

    返回：
        分片列表。
    """
    return [eap_data[i:i + chunk_size] for i in range(0, len(eap_data), chunk_size)] or [b""]
