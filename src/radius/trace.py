# -*- coding: utf-8 -*-
"""
RADIUS 报文收发追踪模块（DEBUG 级）。

职责：
    1. 统一生成报文摘要：报文类型、标识、长度、属性清单、原始 HEX；
    2. 对敏感属性打码（口令类），避免明文口令进入控制台与日志文件；
    3. 按「每个测试任务最多打印多少条」限流，避免 DEBUG 级压测产生日志风暴。

限流说明：
    limit = 0 表示不限流；否则每个任务周期内最多输出 limit 条收发记录，
    超出部分只累计计数，任务结束前由 flush_summary() 输出汇总，
    既不丢观测性，也不会淹没日志。
"""

import threading
from typing import Optional

from ..logging import logger

# 需要打码的标准属性：User-Password(2) / CHAP-Password(3) /
# Tunnel-Password(69) / Message-Authenticator(80)
MASKED_ATTR_IDS = frozenset((2, 3, 69, 80))
# 需要打码的厂商私有属性：(vendor_id, attr_id)
# Microsoft(311) 的 MS-CHAP-Response / MS-CHAP2-Response / LM-Response 等
MASKED_VSA_ATTRS = frozenset(((311, 1), (311, 2), (311, 3)))
# 原始 HEX 最多打印的字节数，超出截断
HEX_LIMIT = 256

_lock = threading.Lock()
_limit = 200
_printed = 0
_skipped = 0


def set_limit(limit: int) -> None:
    """设置每个任务周期的明细输出上限（0 表示不限）。"""
    global _limit
    with _lock:
        _limit = max(0, int(limit or 0))
        _printed = 0
        _skipped = 0


def reset() -> None:
    """重置计数（每次测试任务开始时调用）。"""
    global _printed, _skipped
    with _lock:
        _printed = 0
        _skipped = 0


def allow() -> bool:
    """判断是否允许输出一条明细；不允许时只累计计数。"""
    global _printed, _skipped
    with _lock:
        if _limit and _printed >= _limit:
            _skipped += 1
            return False
        _printed += 1
        return True


def pending_skipped() -> int:
    """返回被限流省略的条数。"""
    with _lock:
        return _skipped


def flush_summary(module: str, stage: str) -> None:
    """输出限流汇总（仅在确实省略过明细时输出）。"""
    skipped = pending_skipped()
    if skipped:
        logger.debug(module, "报文追踪已限流", {
            "stage": stage,
            "omitted": skipped,
            "limit": _limit,
        })


def _is_masked(attr) -> bool:
    """判断属性是否为敏感属性。"""
    if attr.vendor_id:
        return (attr.vendor_id, attr.attr_id) in MASKED_VSA_ATTRS
    return attr.attr_id in MASKED_ATTR_IDS


def _attribute_text(attr) -> str:
    """生成单个属性的展示文本，敏感值打码。"""
    name = attr.name or ("#%s" % attr.attr_id)
    if attr.vendor_id:
        name = "%s(vendor=%s,id=%s)" % (name, attr.vendor_id, attr.attr_id)
    if _is_masked(attr):
        return "%s=<已隐藏 %d 字节>" % (name, len(attr.raw))
    value = attr.value
    if isinstance(value, bytes):
        value = value.hex()
    return "%s=%s" % (name, value)


def summarize(payload: bytes) -> str:
    """
    生成报文摘要文本。

    参数：
        payload: 完整报文字节串

    返回：
        形如 code=Access-Accept;id=1;len=20;attrs=[User-Name=user1;...] 的文本。
    """
    if not payload:
        return "空报文"
    try:
        from .packet import decode_packet
        from ..parser import packet_parser

        packet = packet_parser.enrich(decode_packet(payload))
        items = [_attribute_text(attr) for attr in packet.attributes]
        text = "code=%s;id=%d;len=%d;attrs=[%s]" % (
            packet.code_name, packet.identifier, packet.length, ";".join(items) or "无")
        return text
    except Exception as exc:  # 报文截断/非法时不能让日志把业务带崩
        return "报文解析失败(%s)" % exc


def raw_text(payload: bytes) -> str:
    """生成原始 HEX 文本，超长截断。"""
    if not payload:
        return ""
    if len(payload) <= HEX_LIMIT:
        return payload.hex()
    return "%s...(共 %d 字节)" % (payload[:HEX_LIMIT].hex(), len(payload))


def record_send(module: str, host: str, port: int, identifier: int, payload: bytes,
                response: bytes, elapsed_ms: float, attempt: int,
                retry_count: int, slot: int = 0) -> None:
    """记录一次成功收发。"""
    if not logger.is_debug_enabled() or not allow():
        return
    logger.debug(module, "RADIUS 收发成功", {
        "target": "%s:%s" % (host, port),
        "slot": slot,
        "identifier": identifier,
        "attempt": "%d/%d" % (attempt, retry_count),
        "elapsed_ms": round(elapsed_ms, 3),
        "request": summarize(payload),
        "request_hex": raw_text(payload),
        "response": summarize(response),
        "response_hex": raw_text(response),
    })


def record_timeout(module: str, host: str, port: int, identifier: int, payload: bytes,
                   elapsed_ms: float, attempt: int, retry_count: int,
                   slot: int = 0) -> None:
    """记录一次超时尝试。"""
    if not logger.is_debug_enabled() or not allow():
        return
    logger.debug(module, "RADIUS 收发超时", {
        "target": "%s:%s" % (host, port),
        "slot": slot,
        "identifier": identifier,
        "attempt": "%d/%d" % (attempt, retry_count),
        "elapsed_ms": round(elapsed_ms, 3),
        "request": summarize(payload),
        "request_hex": raw_text(payload),
    })


def record_send_only(module: str, host: str, port: int, payload: bytes,
                     stage: str = "", extra: Optional[dict] = None) -> None:
    """记录一次只发不等待的报文（如探测）。"""
    if not logger.is_debug_enabled() or not allow():
        return
    fields = {
        "target": "%s:%s" % (host, port),
        "stage": stage,
        "request": summarize(payload),
    }
    if extra:
        fields.update(extra)
    logger.debug(module, "RADIUS 发送报文", fields)
