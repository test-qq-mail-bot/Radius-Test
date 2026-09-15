# -*- coding: utf-8 -*-
"""
RADIUS 报文构造模块。

职责：
    1. 构造 Access-Request 与 Accounting-Request 的属性区与完整报文；
    2. 提供计费报文的发送前签名回调（RFC 2866 3 的 Request Authenticator）；
    3. 提供计费流程的 DEBUG 追踪与请求报文回填。

设计说明：
    Accounting-Request 的 Request Authenticator 依赖最终的 Identifier，
    而 Identifier 由 Socket 池在发送前分配并覆写，因此报文先以占位值构造，
    再通过 signer 回调在 Identifier 确定后完成签名。
"""

import random
import time
from typing import List, Optional, Tuple

from ..logging import logger
from . import attributes as attr_mod
from . import authenticator as auth_mod
from . import codes
from . import trace
from .packet import decode_packet, encode_packet

# RADIUS 标准属性编号
ATTR_STATE = 24
ATTR_NAS_PORT = 5
ATTR_NAS_PORT_TYPE = 61
ATTR_CALLED_STATION_ID = 30
ATTR_CALLING_STATION_ID = 31
ATTR_ACCT_AUTHENTIC = 45
ATTR_ACCT_INPUT_OCTETS = 42
ATTR_ACCT_OUTPUT_OCTETS = 43
ATTR_ACCT_SESSION_TIME = 46
ATTR_ACCT_INPUT_PACKETS = 47
ATTR_ACCT_OUTPUT_PACKETS = 48
# 常用可配置属性（Dot1X 接入场景）
ATTR_SERVICE_TYPE = 6
ATTR_FRAMED_IP_ADDRESS = 8
ATTR_NAS_IDENTIFIER = 32
ATTR_CONNECT_INFO = 77
ATTR_NAS_PORT_ID = 87

# Service-Type(6) 常用取值：供前端下拉展示与文本容错解析。
# 说明：NAS-Port(5) 是「端口号（数值）」，NAS-Port-Id(87) 是「端口名称（字符串）」，
# 二者语义完全不同，不可混用。
SERVICE_TYPES = {
    "login": 1,
    "framed": 2,
    "callback-login": 3,
    "callback-framed": 4,
    "outbound": 5,
    "administrative": 6,
    "nas-prompt": 7,
    "authenticate-only": 8,
    "callback-nas-prompt": 9,
    "call-check": 10,
}

# 计费状态类型中文名，供日志阅读
ACCT_STATUS_TEXT = {
    1: "Start", 2: "Stop", 3: "Interim-Update", 7: "Accounting-On", 8: "Accounting-Off",
}


def _random_mac() -> str:
    """生成合法随机终端 MAC（XX-XX-XX-XX-XX-XX 格式）。"""
    return "%02X-%02X-%02X-%02X-%02X-%02X" % tuple(
        random.randint(0, 255) for _ in range(6))


def _index_mac(index: int) -> str:
    """按用户序号生成唯一终端 MAC（本地管理地址段 02-00-...，不会与其他用户重复）。"""
    value = int(index) + 1
    return "02-00-%02X-%02X-%02X-%02X" % (
        (value >> 24) & 0xFF, (value >> 16) & 0xFF,
        (value >> 8) & 0xFF, value & 0xFF,
    )


def _random_nas_port_id() -> str:
    """生成合法随机 NAS-Port-Id(87) 端口名称（如 GigabitEthernet0/0/12）。"""
    return "GigabitEthernet%d/%d" % (random.randint(0, 3), random.randint(0, 47))


def _index_nas_port_id(index: int) -> str:
    """按用户序号生成唯一 NAS-Port-Id(87)（每 48 口视为一张板卡）。"""
    value = int(index)
    return "GigabitEthernet%d/%d" % (value // 48, value % 48)


def _random_nas_identifier() -> str:
    """生成合法随机 NAS-Identifier(32) 主机名（符合 RFC 1123，如 nas-1a2b）。"""
    return "nas-%04x" % random.randint(0, 65535)


def _random_connect_info() -> str:
    """生成合法随机 Connect-Info(77)（如 CONNECT 123456789）。"""
    return "CONNECT %d" % random.randint(100000000, 999999999)


def _random_service_type() -> int:
    """生成合法随机 Service-Type(6) 取值（取 SERVICE_TYPES 内 RFC 2865 定义值 1~10）。"""
    return random.choice(sorted(SERVICE_TYPES.values()))


def _random_framed_ip() -> str:
    """生成合法随机 Framed-IP-Address(8)（RFC 1918 私有段，避免与真实地址冲突）。"""
    return "10.%d.%d.%d" % (random.randint(0, 255), random.randint(0, 255),
                            random.randint(1, 254))


def _index_framed_ip(index: int) -> str:
    """按用户序号唯一生成 Framed-IP-Address(8)（10.0.0.0/8 段递增，封顶 10.255.255.254）。"""
    value = min(int(index) + 1, 0xFFFFFE)
    return "10.%d.%d.%d" % ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


def _index_nas_port(index: int) -> int:
    """按用户序号唯一分配 NAS-Port(5)：第 1 个用户 1000，封顶 65535。"""
    return min(1000 + int(index), 65535)


def resolve_device_fields(dot1x: Optional[dict] = None) -> dict:
    """
    填充「设备级」默认值：NAS-Identifier(32)、Service-Type(6)、Connect-Info(77)。

    设备级字段一次测试只生成一个取值，全部被测用户共用
    （同一台 NAS 的标识与服务类型应当保持一致）。

    参数：
        dot1x: 前端传入的 Dot1X 配置，可为 None

    返回：
        新的 dict（不修改入参）；三个字段留空时写入默认随机合法值。
    """
    dot1x = dict(dot1x or {})
    if not str(dot1x.get("nas_identifier") or "").strip():
        dot1x["nas_identifier"] = _random_nas_identifier()
    if not str(dot1x.get("service_type") or "").strip():
        dot1x["service_type"] = _random_service_type()
    if not str(dot1x.get("connect_info") or "").strip():
        dot1x["connect_info"] = _random_connect_info()
    return dot1x


def resolve_port_fields(dot1x: Optional[dict] = None, index: Optional[int] = None) -> dict:
    """
    填充「端口/终端级」默认值：NAS-Port(5)、NAS-Port-Id(87)、
    终端 MAC(Calling-Station-Id 31)、Framed-IP-Address(8)。

    这些字段与「哪一个用户 / 哪一个接入端口」绑定，因此：
        - 性能测试传入 index 时**按用户序号唯一生成**，避免多用户取值碰撞
          导致服务端把不同会话串成一条；
        - 单用户认证测试不传 index，直接随机生成。

    参数：
        dot1x: Dot1X 配置
        index: 用户在列表中的序号；None 表示随机

    返回：
        新的 dict（不修改入参）；四个字段留空时写入默认合法值。
    """
    dot1x = dict(dot1x or {})
    if not str(dot1x.get("nas_port") or "").strip():
        dot1x["nas_port"] = _index_nas_port(index) if index is not None \
            else random.randint(1, 65535)
    if not str(dot1x.get("nas_port_id") or "").strip():
        dot1x["nas_port_id"] = _index_nas_port_id(index) if index is not None \
            else _random_nas_port_id()
    if not str(dot1x.get("calling_station_id") or "").strip():
        dot1x["calling_station_id"] = _index_mac(index) if index is not None \
            else _random_mac()
    if not str(dot1x.get("framed_ip_address") or "").strip():
        dot1x["framed_ip_address"] = _index_framed_ip(index) if index is not None \
            else _random_framed_ip()
    return dot1x


def resolve_dot1x(dot1x: Optional[dict] = None, index: Optional[int] = None) -> dict:
    """
    统一入口：把 Dot1X 配置补齐为「可直接发送」的完整配置。

    口径（用户确认，2026-09-15）：
        面板上除接入类型与 SSID 外，其余字段**一律可自定义**；
        **留空时用默认生成的合法值发送出去，不存在「留空不发送」**。
        适用字段：NAS-Port(5)、NAS-Port-Id(87)、终端 MAC(31)、
        NAS-Identifier(32)、Service-Type(6)、Framed-IP-Address(8)、Connect-Info(77)。

    本函数是性能测试与全部账号认证测试（用户列表单个/批量、Server 用户测试）
    **共用的唯一口径**，任何测试入口都不得自建字段白名单；
    三个测试入口的面板字段也完全一致（不再对任何入口排除字段）。

    参数：
        dot1x: 前端传入的 Dot1X 配置，可为 None 或空字典
        index: 用户在列表中的序号；性能测试传入，单用户测试不传

    返回：
        新的 dict（不修改入参）。
    """
    return resolve_port_fields(resolve_device_fields(dot1x), index)


def _service_type_value(raw) -> Optional[int]:
    """
    解析 Service-Type(6) 取值。

    支持数字（1~15）与文本键（见 SERVICE_TYPES）；
    非法值返回 None，表示不发送该属性。
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, int):
        value = raw
    else:
        text = str(raw).strip()
        if text.isdigit():
            value = int(text)
        else:
            return SERVICE_TYPES.get(text.lower())
    return value if 1 <= value <= 15 else None


def _append_common_attributes(result: List[Tuple[int, bytes]], dot1x: dict) -> None:
    """
    追加常用可配置属性。

    含 NAS-Identifier(32)、Service-Type(6)、Framed-IP-Address(8)、Connect-Info(77)。

    说明（2026-09-15 口径）：传入的 dot1x 应已由 resolve_dot1x / resolve_device_fields /
    resolve_port_fields 补齐默认值，正常路径下这四个属性一定有值。此处仍保留空值判断，
    仅作为「调用方绕过 resolve 层」时的兜底，避免构造出非法报文
    （Service-Type 取值非法时同样跳过，见 _service_type_value）。
    """
    nas_identifier = str(dot1x.get("nas_identifier") or "").strip()
    if nas_identifier:
        result.append((ATTR_NAS_IDENTIFIER, nas_identifier.encode("utf-8")))

    service_type = _service_type_value(dot1x.get("service_type"))
    if service_type is not None:
        result.append((ATTR_SERVICE_TYPE, service_type.to_bytes(4, "big")))

    framed_ip = str(dot1x.get("framed_ip_address") or "").strip()
    if framed_ip:
        try:
            result.append((ATTR_FRAMED_IP_ADDRESS,
                           codes.encode_value(codes.TYPE_IPADDR, framed_ip)))
        except Exception as exc:
            # 地址非法时记录告警并跳过，而不是让整个测试报错
            logger.warning("radius", "Framed-IP-Address 编码失败，已跳过该属性", {
                "framed_ip_address": framed_ip,
                "error": str(exc),
            })

    connect_info = str(dot1x.get("connect_info") or "").strip()
    if connect_info:
        result.append((ATTR_CONNECT_INFO, connect_info.encode("utf-8")))


def base_attributes(server: dict, username: str,
                    dot1x: Optional[dict] = None) -> List[Tuple[int, bytes]]:
    """
    构造请求的基础属性。

    包含：User-Name、NAS-IP-Address（配置了才带）、NAS-Port、
    Called-Station-Id、Calling-Station-Id，以及 Dot1X 配置时的 NAS-Port-Type。

    dot1x：可选的 Dot1X 接入配置（账号认证测试与性能测试共用），结构：
        {
            "access_type": "wired" | "wireless",
            "ssid": str,                 # 仅无线用，可空，默认 Radius-Test
            "ap_mac": str,               # 仅无线用，Called-Station-Id 前缀，默认全 0
            "nas_port": int | str,       # NAS-Port(5) 端口号（数值）
            "nas_port_id": str,          # NAS-Port-Id(87) 端口名称（字符串）
            "calling_station_id": str,   # 终端 MAC
            "nas_identifier": str,       # NAS-Identifier(32)
            "service_type": int | str,   # Service-Type(6)
            "framed_ip_address": str,    # Framed-IP-Address(8)
            "connect_info": str,         # Connect-Info(77)
        }

    口径（2026-09-15，用户确认）：
        dot1x 应在进入本函数前由 builder.resolve_dot1x() 补齐，
        **NAS-Port / NAS-Port-Id / 终端 MAC / NAS-Identifier / Connect-Info
        留空一律使用默认生成的合法值发送，不存在「留空不发送」**。
        本函数仅对真正未配置（dot1x 为 None，例如直接调 API 且不带该字段）
        的情况沿用原硬编码属性以保持向后兼容。
        注：NAS-Port 与终端 MAC 仍保留兜底随机，防止调用方漏过 resolve 层。
    """
    result = [(codes.ATTR_USER_NAME, username.encode("utf-8"))]
    nas_ip = str(server.get("nas_ip_address", "")).strip()
    if nas_ip:
        try:
            result.append((codes.ATTR_NAS_IP_ADDRESS,
                           codes.encode_value(codes.TYPE_IPADDR, nas_ip)))
        except Exception as exc:
            # 地址非法时记录告警，而不是静默丢弃
            logger.warning("radius", "NAS IP 地址编码失败，已跳过该属性", {
                "nas_ip": nas_ip,
                "error": str(exc),
            })

    # Dot1X 接入配置：账号认证测试与性能测试均可传入；为 None 时维持原硬编码
    if dot1x:
        access_type = str(dot1x.get("access_type") or "wired").lower()
        # NAS-Port(5)：用户自定义或随机合法整数（1~65535）
        nas_port = dot1x.get("nas_port")
        if nas_port is None or nas_port == "":
            nas_port = random.randint(1, 65535)
        else:
            nas_port = int(nas_port)
        result.append((ATTR_NAS_PORT, int(nas_port).to_bytes(4, "big")))
        # Calling-Station-Id(31) 终端 MAC：用户自定义或随机合法 MAC
        mac = str(dot1x.get("calling_station_id") or "").strip()
        if not mac:
            mac = _random_mac()
        result.append((ATTR_CALLING_STATION_ID, mac.encode("utf-8")))
        # NAS-Port-Id(87) 端口名称：字符串，与 NAS-Port(5) 完全不同，留空则不发送
        nas_port_id = str(dot1x.get("nas_port_id") or "").strip()
        if nas_port_id:
            result.append((ATTR_NAS_PORT_ID, nas_port_id.encode("utf-8")))
        # NAS-Port-Type(61) 区分接入介质；Called-Station-Id(30) 按接入类型构造
        if access_type == "wireless":
            result.append((ATTR_NAS_PORT_TYPE, (19).to_bytes(4, "big")))  # IEEE-802.11
            ssid = str(dot1x.get("ssid") or "").strip() or "Radius-Test"
            ap_mac = (str(dot1x.get("ap_mac") or "00-00-00-00-00-00").strip()
                      or "00-00-00-00-00-00")
            result.append((ATTR_CALLED_STATION_ID,
                           ("%s:%s" % (ap_mac, ssid)).encode("utf-8")))
        else:
            result.append((ATTR_NAS_PORT_TYPE, (15).to_bytes(4, "big")))  # Ethernet
            result.append((ATTR_CALLED_STATION_ID, b"00-00-00-00-00-00"))
        _append_common_attributes(result, dot1x)
    else:
        # 原硬编码行为（性能测试 / 未配置 Dot1X 时保持兼容）
        result.append((ATTR_NAS_PORT, (1).to_bytes(4, "big")))
        result.append((ATTR_CALLED_STATION_ID, b"00-00-00-00-00-00:Radius-Test"))
        result.append((ATTR_CALLING_STATION_ID, b"02-00-00-00-00-01"))
    return result


def build_access_packet(code: int, request_authenticator: bytes,
                        attributes: list, secret: bytes) -> bytes:
    """
    构造 Access-Request 完整报文。

    Message-Authenticator（属性 80）仅在报文包含 EAP-Message（属性 79）时追加，
    符合 RFC 2869 5.14「仅当使用 EAP 时必须携带」的要求。
    PAP / CHAP / MS-CHAP 等非 EAP 报文不携带该属性，
    避免部分服务端对无法校验的 Message-Authenticator 静默丢弃导致超时。
    """
    attribute_bytes = attr_mod.encode_attributes(attributes)
    has_eap = any(attr_id == codes.ATTR_EAP_MESSAGE for attr_id, _ in attributes)
    if has_eap:
        attribute_bytes += auth_mod.build_message_authenticator_placeholder()
        length = 20 + len(attribute_bytes)
        mac = auth_mod.compute_message_authenticator(
            code, 0, length, request_authenticator, attribute_bytes, secret)
        attribute_bytes = auth_mod.replace_message_authenticator(attribute_bytes, mac)
    return encode_packet(code, 0, request_authenticator, attribute_bytes)


def build_accounting_packet(attributes: list, use_message_authenticator: bool) -> bytes:
    """
    构造 Accounting-Request 骨架（认证器为 16 字节零占位）。

    真实取值由 accounting_signer() 在发送前按 RFC 2866 计算。
    """
    attribute_bytes = attr_mod.encode_attributes(attributes)
    if use_message_authenticator:
        attribute_bytes += auth_mod.build_message_authenticator_placeholder()
    return encode_packet(codes.ACCOUNTING_REQUEST, 0,
                         bytes(auth_mod.AUTHENTICATOR_LENGTH), attribute_bytes)


def accounting_signer(secret: bytes, use_message_authenticator: bool):
    """
    返回计费报文的发送前签名回调。

    算法（RFC 2866 3）：
        Request Authenticator = MD5(Code + Identifier + Length + 16 个零字节 + 属性 + 密钥)
    若启用 Message-Authenticator（RFC 3579 3.2），则在算出 Request Authenticator
    之后再对其余全部字段做 HMAC-MD5。
    """

    def sign(payload: bytes) -> bytes:
        identifier = payload[1]
        body = payload[20:]
        length = len(payload)
        request_auth = auth_mod.compute_accounting_request_authenticator(
            codes.ACCOUNTING_REQUEST, identifier, length, body, secret)
        if use_message_authenticator:
            mac = auth_mod.compute_message_authenticator(
                codes.ACCOUNTING_REQUEST, identifier, length,
                request_auth, body, secret)
            body = auth_mod.replace_message_authenticator(body, mac)
        return payload[:4] + request_auth + body

    return sign


def remember_request(result, sent: dict) -> None:
    """
    用真实发出的字节重建请求对象。

    说明：
        Accounting-Request 的 Identifier 与 Request Authenticator 都在发送时才确定，
        展示骨架（占位认证器）会失真，因此用发送回调捕获的真实字节覆盖。
    """
    if sent.get("payload"):
        result.request_packet = decode_packet(sent["payload"])


def trace_accounting(username: str, acct_status_type: int, session_id: str,
                     sent: dict, started: float, result_name: str) -> None:
    """
    输出一条计费流程的 DEBUG 概览。

    报文的字节级收发明细由 socket_pool.trace 统一输出，
    此处补充业务语义（用户名、计费类型、会话 ID），便于对照排查。
    """
    if not logger.is_debug_enabled() or not trace.allow():
        return
    logger.debug("radius", "计费报文处理完成", {
        "username": username,
        "acct_status": "%s(%d)" % (ACCT_STATUS_TEXT.get(acct_status_type, "未知"),
                                   acct_status_type),
        "session_id": session_id,
        "result": result_name or "无响应",
        "request_bytes": len(sent.get("payload") or b""),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    })
