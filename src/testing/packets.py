# -*- coding: utf-8 -*-
"""
RADIUS 报文落库模块。

职责：
    把一次 RADIUS 交互的请求/响应报文及其属性解析结果写入数据库，
    供测试任务链路（性能测试）与单次测试链路（用户列表「测试」）共同复用。

口径：
    1. 属性匹配：落库前一律经 packet_parser.enrich() 做模板匹配，
       认证报文与计费报文走同一条路径，口径一致，
       不再出现「计费报文属性全是未知属性」的缺陷（需求3）。
    2. 同类合并：同一任务 + 用户下，同 packet_type 的报文只保留最新一条。
       性能测试期间 Interim-Update 会反复刷新，若逐条追加会把详情页堆满
       重复报文；因此写入前先删同类型旧记录（需求2）。
       删除与写入共用同一条异步队列，天然保证「先删旧、再写新」。

说明：
    报文 ID 采用预分配方式（dao.allocate_packet_ids），避免写入走异步
    批量队列时属性表无法引用报文 ID 的竞态问题。
"""

from ..common import time_util
from ..database import dao


def _enrich(packet):
    """
    落库前统一做模板匹配，填充属性名称、类型与值。

    幂等：enrich 按 attr_id + vendor_id 重新匹配，
    对已匹配过的报文重复调用不产生副作用。

    参数：
        packet: RadiusPacket，为 None 时原样返回
    """
    if packet is None:
        return None
    from ..parser import packet_parser

    return packet_parser.enrich(packet)


def _write_pairs(task_id: str, username: str, server_name: str, pairs) -> None:
    """
    按「同类型只留最新」口径写入一组报文。

    参数：
        pairs: [(packet_type, packet), ...]，调用方负责剔除 None
    """
    if not pairs:
        return
    now = time_util.format_log_time()
    packet_ids = dao.allocate_packet_ids(len(pairs))
    for (packet_type, packet), packet_id in zip(pairs, packet_ids):
        packet = _enrich(packet)
        # 先合并同类型旧报文，再写新报文（同一队列 FIFO，顺序有保证）
        dao.delete_packets_by_type(task_id, username, packet_type)
        dao.save_packet({
            "task_id": task_id,
            "username": username,
            "server": server_name,
            "packet_type": packet_type,
            "packet_time": now,
            "raw_packet": packet.raw.hex(),
            "parse_status": packet.parse_status,
            "parse_error": packet.parse_error,
        }, packet_id=packet_id)
        save_attributes(packet, packet_id)


def save_packets(task_id: str, username: str, server_name: str,
                 request_packet, response_packet) -> None:
    """
    保存一次认证交互的请求与响应报文及其属性。

    packet_type 形如 request-Access-Request / response-Access-Accept。

    参数：
        request_packet / response_packet: RadiusPacket，为 None 时跳过
    """
    pairs = []
    for label, packet in (("request", request_packet), ("response", response_packet)):
        if packet is not None:
            pairs.append(("%s-%s" % (label, packet.code_name), packet))
    _write_pairs(task_id, username, server_name, pairs)


# 计费报文状态类型 -> 可读名称，用于详情页按类型分组（需求2/4）
_ACCT_STATUS_NAMES = {
    1: "Start",
    2: "Stop",
    3: "Interim",
}


def save_accounting(task_id: str, username: str, server_name: str,
                    result, status_type: int) -> None:
    """
    保存一次计费交互的报文（按 Acct-Status-Type 区分 Start / Interim / Stop）。

    packet_type 形如 request-Accounting-Start / response-Accounting-Start，
    使前端能按「认证 / Start / Interim / Stop」四组直出（需求4）。

    参数：
        result: RadiusClient.send_accounting 的返回对象
        status_type: 1=Start / 2=Stop / 3=Interim-Update
    """
    if result is None:
        return
    name = "Accounting-" + _ACCT_STATUS_NAMES.get(int(status_type), "Other")
    pairs = []
    for label in ("request", "response"):
        packet = getattr(result, "%s_packet" % label, None)
        if packet is not None:
            pairs.append(("%s-%s" % (label, name), packet))
    _write_pairs(task_id, username, server_name, pairs)


def save_attributes(packet, packet_id: int) -> None:
    """
    保存单条报文的属性解析结果。

    命中模板的属性按模板逐条展开（一条属性命中多个模板时全部列出）；
    未命中的以 Unknown 兜底，保留原始十六进制值便于排查。
    """
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
