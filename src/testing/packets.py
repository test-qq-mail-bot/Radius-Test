# -*- coding: utf-8 -*-
"""
RADIUS 报文落库模块。

职责：
    把一次 RADIUS 交互的请求/响应报文及其属性解析结果写入数据库，
    供测试任务链路与单次测试链路（用户列表「测试」）共同复用。

说明：
    报文 ID 采用预分配方式（dao.allocate_packet_ids），避免写入走异步
    批量队列时属性表无法引用报文 ID 的竞态问题。
"""

from ..common import time_util
from ..database import dao


def save_packets(task_id: str, username: str, server_name: str,
                 request_packet, response_packet) -> None:
    """
    保存请求与响应报文及其属性。

    流程：
        1. 预分配报文 ID；
        2. 写入报文；
        3. 用同一批 ID 写入属性，建立关联关系。

    参数：
        request_packet / response_packet: RadiusPacket，为 None 时跳过
    """
    pairs = [("request", request_packet), ("response", response_packet)]
    pairs = [(label, packet) for label, packet in pairs if packet is not None]
    if not pairs:
        return
    now = time_util.format_log_time()
    packet_ids = dao.allocate_packet_ids(len(pairs))
    for (label, packet), packet_id in zip(pairs, packet_ids):
        dao.save_packet({
            "task_id": task_id,
            "username": username,
            "server": server_name,
            "packet_type": "%s-%s" % (label, packet.code_name),
            "packet_time": now,
            "raw_packet": packet.raw.hex(),
            "parse_status": packet.parse_status,
            "parse_error": packet.parse_error,
        }, packet_id=packet_id)
        save_attributes(packet, packet_id)


def save_attributes(packet, packet_id: int) -> None:
    """保存单条报文的属性解析结果。"""
    if packet is None:
        return
    rows = []
    for attribute in packet.attributes:
        if attribute.matches:
            for match in attribute.matches:
                rows.append({
                    "packet_id": packet_id,
                    "attribute_id": attribute.attr_id,
                    "radius_template": match["template"],
                    "name": match["name"],
                    "name_zh": match["name_zh"],
                    "type": match["type"],
                    "value": _stringify(match.get("type"), attribute.raw),
                    "vendor_id": attribute.vendor_id,
                })
        else:
            rows.append({
                "packet_id": packet_id,
                "attribute_id": attribute.attr_id,
                "radius_template": "Unknown",
                "name": "Unknown",
                "name_zh": "未知属性",
                "type": "unknown",
                "value": attribute.raw.hex(),
                "vendor_id": attribute.vendor_id,
            })
    dao.save_attributes(rows)


def _stringify(type_name: str, raw: bytes) -> str:
    """按类型把属性原始值转换为存储文本。"""
    from ..radius.codes import decode_value

    value = decode_value(type_name, raw)
    return value if isinstance(value, str) else str(value)
