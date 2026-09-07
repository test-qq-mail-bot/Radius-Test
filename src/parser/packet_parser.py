# -*- coding: utf-8 -*-
"""
RADIUS 报文解析模块。

职责（项目书 17.2）：
    先解析 RADIUS 报文，再遍历所有已经加载的 Radius 模板进行匹配。
    不能先根据某个 Radius 模板决定如何解析报文。

流程：
    收到报文
        -> 解析基础报文头部
        -> 解析 Attributes
        -> 解析 VSA
        -> 得到属性编号
        -> 遍历全部已加载模板
        -> 编号匹配则生成匹配模板，否则标记 Unknown
        -> 输出属性信息

要点：
    1. 一个属性命中多个模板时必须全部列出；
    2. 未知属性不得丢弃，标记为 Unknown 并保留原始值。
"""

from typing import List

from ..dictionary.loader import get_store
from ..logging import logger
from ..radius.codes import TYPE_UNKNOWN, decode_value
from ..radius.packet import RadiusPacket

# 未知属性展示用常量
UNKNOWN_TEMPLATE = "Unknown"
UNKNOWN_NAME = "Unknown"
UNKNOWN_NAME_ZH = "未知属性"


def enrich(packet: RadiusPacket) -> RadiusPacket:
    """
    对已解析的报文做模板匹配，填充属性的名称与值。

    参数：
        packet: 已经完成字节级解析的报文对象

    返回：
        同一个报文对象（原地填充）。
    """
    store = get_store()
    for attribute in packet.attributes:
        definitions = store.match(attribute.attr_id, attribute.vendor_id)
        if not definitions:
            attribute.attr_type = TYPE_UNKNOWN
            attribute.name = UNKNOWN_NAME
            attribute.name_zh = UNKNOWN_NAME_ZH
            attribute.value = attribute.raw.hex()
            attribute.matches = []
            continue
        # 命中多个模板时全部列出
        attribute.matches = [
            {
                "template": d.template,
                "vendor": d.vendor,
                "vendor_id": d.vendor_id,
                "name": d.name,
                "name_zh": d.name_zh,
                "type": d.type,
                "desc": d.desc,
            }
            for d in definitions
        ]
        # 展示取第一个命中项，详情页可查看全部
        primary = definitions[0]
        attribute.attr_type = primary.type
        attribute.name = primary.name
        attribute.name_zh = primary.name_zh
        attribute.value = decode_value(primary.type, attribute.raw)
    return packet


def parse_bytes(data: bytes) -> RadiusPacket:
    """
    一步完成字节解析与模板匹配。

    参数：
        data: 原始报文字节串

    返回：
        已完成匹配的报文对象。
    """
    from ..radius.packet import decode_packet

    packet = decode_packet(data)
    return enrich(packet)


def describe(packet: RadiusPacket) -> dict:
    """
    生成解析结果摘要，供详情页展示。

    返回：
        字典，含 code_name、identifier、length、parse_status、attributes。
    """
    if packet is None:
        return {}
    return packet.to_dict()


def parse_hex_string(text: str) -> RadiusPacket:
    """
    解析十六进制字符串形式的报文。

    参数：
        text: 十六进制字符串，可含空格与 0x 前缀

    返回：
        已完成匹配的报文对象。
    """
    cleaned = "".join(ch for ch in text if ch in "0123456789abcdefABCDEF")
    if len(cleaned) % 2 != 0:
        raise ValueError("十六进制字符串长度必须为偶数")
    return parse_bytes(bytes.fromhex(cleaned))


def summarize_attributes(packet: RadiusPacket) -> List[dict]:
    """
    输出属性摘要列表。

    返回：
        每项含 template / name / name_zh / type / value。
    """
    if packet is None:
        return []
    return [
        {
            "template": a.matches[0]["template"] if a.matches else UNKNOWN_TEMPLATE,
            "name": a.name,
            "name_zh": a.name_zh,
            "type": a.attr_type,
            "value": a.value if isinstance(a.value, (str, int)) else str(a.value),
        }
        for a in packet.attributes
    ]
