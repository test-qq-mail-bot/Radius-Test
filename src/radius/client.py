# -*- coding: utf-8 -*-
"""
RADIUS 客户端模块。

职责：
    1. 驱动 Access-Request 认证（PAP / CHAP / MS-CHAP v1 / MS-CHAP v2 / EAP-MD5）；
    2. 驱动 EAP-MD5 多轮交互；
    3. 发送 Accounting-Request（Start / Interim-Update / Stop）；
    4. 统一返回结构化的测试结果。

说明：
    本模块不负责并发控制与限速，相关能力由 performance 与 testing 包提供；
    报文构造细节见 radius.builder。
"""

import time
from typing import Optional

from ..authentication import chap as chap_mod
from ..authentication import eap as eap_mod
from ..authentication import mschap as mschap_mod
from ..authentication import pap as pap_mod
from ..common import net_util, uuid_util
from ..common.errors import RadiusError, RadiusTimeout
from ..logging import logger
from . import attributes as attr_mod
from . import authenticator as auth_mod
from . import builder
from . import codes
from .packet import RadiusPacket, decode_packet

# EAP 多轮交互最大轮次，防止服务端异常导致死循环
MAX_EAP_ROUNDS = 12
# RADIUS 标准属性编号（State 仅 EAP 多轮交互使用）
ATTR_STATE = 24


class RadiusResult:
    """
    单次 RADIUS 交互结果。

    属性：
        success: 是否成功（Access-Accept / Accounting-Response）
        code: 响应报文类型
        code_name: 响应报文类型名称
        response_time_ms: 响应耗时（毫秒）
        error: 错误信息，成功时为空
        request_packet: 请求报文对象
        response_packet: 响应报文对象
        eap_rounds: EAP 交互轮次
        authenticator_valid: 响应认证器校验结果
        extra: 附加信息（如 MS-CHAP2-Success 校验结果）
    """

    __slots__ = ("success", "code", "code_name", "response_time_ms", "error",
                 "request_packet", "response_packet", "eap_rounds",
                 "authenticator_valid", "extra")

    def __init__(self):
        self.success = False
        self.code = 0
        self.code_name = ""
        self.response_time_ms = 0.0
        self.error = ""
        self.request_packet: Optional[RadiusPacket] = None
        self.response_packet: Optional[RadiusPacket] = None
        self.eap_rounds = 0
        self.authenticator_valid = False
        self.extra: dict = {}


class RadiusClient:
    """
    RADIUS 客户端。

    参数：
        socket_manager: UDP Socket 池管理器
    """

    def __init__(self, socket_manager):
        self._manager = socket_manager

    # ---------------- 内部工具 ----------------

    @staticmethod
    def _secret(server: dict) -> bytes:
        """取共享密钥字节串。"""
        return str(server.get("shared_secret", "")).encode("utf-8")

    @staticmethod
    def _resolve_address(server: dict) -> str:
        """解析目标地址，主机名解析失败时原样返回。"""
        return net_util.resolve_host(str(server.get("server_address", "")))

    @staticmethod
    def _auth_effective(server: dict) -> dict:
        """认证使用专用 RADIUS 认证服务器；缺省回退通用 server_address / shared_secret。"""
        eff = dict(server)
        eff["server_address"] = server.get("authentication_server_address") or server.get("server_address") or ""
        eff["shared_secret"] = server.get("authentication_secret") or server.get("shared_secret") or ""
        return eff

    @staticmethod
    def _acct_effective(server: dict) -> dict:
        """计费使用专用 RADIUS 计费服务器；缺省回退通用 server_address / shared_secret。"""
        eff = dict(server)
        eff["server_address"] = server.get("accounting_server_address") or server.get("server_address") or ""
        eff["shared_secret"] = server.get("accounting_secret") or server.get("shared_secret") or ""
        return eff

    def _base_attributes(self, server: dict, username: str) -> list:
        """构造认证请求的基础属性（实现见 radius.builder）。"""
        return builder.base_attributes(server, username)

    def _build_packet(self, code: int, request_authenticator: bytes,
                      attributes: list, secret: bytes) -> bytes:
        """构造完整报文，含 EAP 场景下的 Message-Authenticator（实现见 radius.builder）。"""
        return builder.build_access_packet(code, request_authenticator, attributes, secret)

    async def _send(self, server: dict, packet: bytes, port: int,
                    signer=None, on_sent=None) -> bytes:
        """
        发送报文并返回响应字节串。

        参数：
            signer: 发送前签名回调（Identifier 覆写后调用）
            on_sent: 报文真正发出后的回调，用于取回最终字节串
        """
        host = self._resolve_address(server)
        timeout = float(server.get("timeout") or 5.0)
        retry = int(server.get("retry_count") or 3)
        source_address = str(server.get("source_address") or "").strip()
        return await self._manager.send_request(
            packet, host, port, timeout, retry, source_address,
            signer=signer, on_sent=on_sent)

    # ---------------- 认证 ----------------

    async def authenticate(self, server: dict, username: str, password: str,
                           protocol: str, peer_challenge_bytes: int = 8) -> RadiusResult:
        """
        执行一次完整认证。

        参数：
            server: RADIUS Server 配置字典
            username: 用户名
            password: 明文密码
            protocol: pap / chap / mschap / mschapv2 / eap-md5
            peer_challenge_bytes: MS-CHAP 对端挑战值字节数

        返回：
            RadiusResult 对象。
        """
        started = time.perf_counter()
        result = RadiusResult()
        protocol = (protocol or "pap").lower()
        if protocol not in ("pap", "chap", "mschap", "mschapv2", "eap-md5"):
            raise RadiusError("不支持的认证协议", "协议=%s" % protocol)

        # 路由到专用 RADIUS 认证服务器（缺省回退通用 server_address / shared_secret）
        effective = self._auth_effective(server)
        request_auth = auth_mod.new_request_authenticator()
        secret = self._secret(effective)
        attributes = self._base_attributes(effective, username)

        if protocol == "pap":
            attributes.append((codes.ATTR_USER_PASSWORD,
                               pap_mod.build_pap_password(password, secret, request_auth)))
        elif protocol == "chap":
            challenge = chap_mod.new_chap_challenge(16)
            chap_id = chap_mod.new_chap_id()
            attributes.append((60, challenge))
            attributes.append((codes.ATTR_CHAP_PASSWORD,
                               chap_mod.build_chap_password(chap_id, password, challenge)))
        elif protocol == "mschap":
            data = mschap_mod.build_mschap_v1(username, password, peer_challenge_bytes)
            attributes.append((
                codes.ATTR_VENDOR_SPECIFIC,
                attr_mod.encode_vsa(mschap_mod.VENDOR_ID_MICROSOFT, [
                    (mschap_mod.MS_ATTR_CHAP_CHALLENGE, data["challenge"]),
                    (mschap_mod.MS_ATTR_CHAP_RESPONSE, data["response"]),
                ]),
            ))
            result.extra["mschap_challenge"] = data["challenge"].hex()
        elif protocol == "mschapv2":
            data = mschap_mod.build_mschap_v2(username, password, peer_challenge_bytes)
            attributes.append((
                codes.ATTR_VENDOR_SPECIFIC,
                attr_mod.encode_vsa(mschap_mod.VENDOR_ID_MICROSOFT, [
                    (mschap_mod.MS_ATTR_CHAP_CHALLENGE, data["challenge"]),
                    (mschap_mod.MS_ATTR_CHAP2_RESPONSE, data["response"]),
                ]),
            ))
            result.extra["mschap_challenge"] = data["challenge"].hex()
            result.extra["mschap_peer_challenge"] = data["peer_challenge"].hex()
            result.extra["mschap_expected_success"] = mschap_mod.generate_authenticator_response(
                password, data["nt_response"], data["peer_challenge"],
                data["challenge"], username,
            )

        packet = self._build_packet(codes.ACCESS_REQUEST, request_auth, attributes, secret)
        request_packet = decode_packet(packet)
        result.request_packet = request_packet

        if protocol == "eap-md5":
            return await self._run_eap_md5(effective, username, password, request_auth,
                                           secret, attributes, result, started)

        port = int(effective.get("authentication_port") or 1812)
        try:
            response = await self._send(effective, packet, port)
        except RadiusTimeout as exc:
            result.response_time_ms = (time.perf_counter() - started) * 1000
            result.error = "超时；%s" % exc.detail
            result.code_name = "Timeout"
            return result
        except RadiusError as exc:
            result.response_time_ms = (time.perf_counter() - started) * 1000
            result.error = str(exc)
            return result
        return self._finalize_auth(result, request_auth, response, secret, started)

    async def _run_eap_md5(self, server: dict, username: str, password: str,
                           request_auth: bytes, secret: bytes, base_attributes: list,
                           result: RadiusResult, started: float) -> RadiusResult:
        """
        驱动 EAP-MD5 多轮交互。

        流程：
            1. 发送 EAP-Response/Identity；
            2. 收到 Access-Challenge 后按 EAP 类型应答：
               Identity -> 再次回应 Identity
               Notification -> 回应空 Notification
               MD5-Challenge -> 回应 MD5 响应
            3. 直到收到 Access-Accept / Access-Reject。
        """
        port = int(server.get("authentication_port") or 1812)
        state = b""
        attributes = list(base_attributes) + [
            (codes.ATTR_EAP_MESSAGE,
             eap_mod.build_identity_response(0, username)[:253]),
        ]
        last_request = b""
        for round_index in range(1, MAX_EAP_ROUNDS + 1):
            request_auth = auth_mod.new_request_authenticator()
            # 每轮重新构造（State 与 EAP-Message 变化）
            payload = list(base_attributes)
            if state:
                payload.append((ATTR_STATE, state))
            payload.append((codes.ATTR_EAP_MESSAGE, attributes[-1][1]))
            packet = self._build_packet(codes.ACCESS_REQUEST, request_auth, payload, secret)
            last_request = packet
            try:
                response = await self._send(server, packet, port)
            except RadiusTimeout as exc:
                result.response_time_ms = (time.perf_counter() - started) * 1000
                result.error = "EAP 第 %d 轮超时；%s" % (round_index, exc.detail)
                result.code_name = "Timeout"
                return result
            packet_obj = decode_packet(response)
            if packet_obj.code == codes.ACCESS_CHALLENGE:
                state_attr = packet_obj.find(ATTR_STATE)
                if state_attr is not None:
                    state = state_attr.raw
                eap_data = attr_mod.split_eap_messages(packet_obj.attributes)
                parsed = eap_mod.decode_eap(eap_data)
                eap_id = parsed["identifier"]
                if parsed["type"] == eap_mod.EAP_TYPE_MD5_CHALLENGE:
                    challenge = parsed["value"][1:17]
                    response_eap = eap_mod.build_md5_challenge_response(
                        eap_id, password, challenge)
                elif parsed["type"] == eap_mod.EAP_TYPE_NOTIFICATION:
                    response_eap = eap_mod.build_notification_response(eap_id)
                else:
                    response_eap = eap_mod.build_identity_response(eap_id, username)
                attributes = [(codes.ATTR_EAP_MESSAGE, response_eap[:253])]
                result.eap_rounds = round_index
                continue
            # 终结报文
            result.request_packet = decode_packet(last_request)
            return self._finalize_auth(result, request_auth, response, secret, started)
        result.response_time_ms = (time.perf_counter() - started) * 1000
        result.error = "EAP 交互轮次超过上限 %d" % MAX_EAP_ROUNDS
        return result

    def _finalize_auth(self, result: RadiusResult, request_auth: bytes,
                       response: bytes, secret: bytes, started: float) -> RadiusResult:
        """解析认证响应并填充结果对象。"""
        result.response_time_ms = (time.perf_counter() - started) * 1000
        packet = decode_packet(response)
        result.response_packet = packet
        result.code = packet.code
        result.code_name = packet.code_name
        result.success = packet.code == codes.ACCESS_ACCEPT
        # 校验响应认证器
        attribute_bytes = packet.raw[20:] if len(packet.raw) > 20 else b""
        result.authenticator_valid = auth_mod.verify_response_authenticator(
            packet.code, packet.identifier, packet.length,
            request_auth, attribute_bytes, secret, packet.authenticator,
        )
        if packet.code == codes.ACCESS_REJECT:
            result.error = "服务器拒绝（Access-Reject）"
        elif packet.code not in (codes.ACCESS_ACCEPT, codes.ACCESS_REJECT):
            result.error = "未预期的响应类型：%s" % packet.code_name
        return result

    # ---------------- 计费 ----------------

    async def send_accounting(self, server: dict, username: str,
                              acct_status_type: int, session_id: str = None,
                              session_time: int = 0, input_octets: int = 0,
                              output_octets: int = 0,
                              message_authenticator: bool = False,
                              timeout: float = 0.0,
                              retry_count: int = 0) -> RadiusResult:
        """
        发送一次 Accounting-Request。

        参数：
            server: RADIUS Server 配置
            username: 用户名
            acct_status_type: 1=Start / 2=Stop / 3=Interim-Update
            session_id: 计费会话 ID，未提供时自动生成
            session_time: 会话时长（秒）
            input_octets: 入方向字节数
            output_octets: 出方向字节数
            message_authenticator: 是否附加 Message-Authenticator（部分 NAC 强制要求）
            timeout: 单次等待超时（秒），0 表示沿用 Server 配置
            retry_count: 重试次数，0 表示沿用 Server 配置

        返回：
            RadiusResult 对象。

        说明：
            Request Authenticator 不能使用随机数（RFC 2866 3），
            必须按 MD5(Code + Identifier + Length + 16 个零字节 + 属性 + 密钥) 计算；
            由于 Identifier 在发送时才由 Socket 池分配，签名通过 signer 回调完成。
        """
        started = time.perf_counter()
        result = RadiusResult()
        # 路由到专用 RADIUS 计费服务器（缺省回退通用 server_address / shared_secret）
        effective = self._acct_effective(server)
        if timeout and timeout > 0:
            effective["timeout"] = float(timeout)
        if retry_count and retry_count > 0:
            effective["retry_count"] = int(retry_count)
        secret = self._secret(effective)
        session_id = session_id or uuid_util.new_radius_session_id()
        attributes = self._base_attributes(effective, username)
        attributes.append((codes.ATTR_ACCT_STATUS_TYPE, acct_status_type.to_bytes(4, "big")))
        attributes.append((codes.ATTR_ACCT_SESSION_ID, session_id.encode("utf-8")))
        attributes.append((builder.ATTR_ACCT_AUTHENTIC, (1).to_bytes(4, "big")))
        if acct_status_type in (codes.ACCT_STATUS_STOP, codes.ACCT_STATUS_INTERIM_UPDATE):
            attributes.append((builder.ATTR_ACCT_SESSION_TIME, int(session_time).to_bytes(4, "big")))
            attributes.append((builder.ATTR_ACCT_INPUT_OCTETS, int(input_octets).to_bytes(4, "big")))
            attributes.append((builder.ATTR_ACCT_OUTPUT_OCTETS, int(output_octets).to_bytes(4, "big")))
            attributes.append((builder.ATTR_ACCT_INPUT_PACKETS, (1).to_bytes(4, "big")))
            attributes.append((builder.ATTR_ACCT_OUTPUT_PACKETS, (1).to_bytes(4, "big")))
        packet = builder.build_accounting_packet(attributes, message_authenticator)
        result.request_packet = decode_packet(packet)
        port = int(effective.get("accounting_port") or 1813)
        signer = builder.accounting_signer(secret, message_authenticator)
        sent = {}

        def remember(payload: bytes) -> None:
            """记下真实发出的报文，供结果展示与报文落库使用。"""
            sent["payload"] = payload

        try:
            response = await self._send(effective, packet, port,
                                        signer=signer, on_sent=remember)
        except RadiusTimeout as exc:
            builder.remember_request(result, sent)
            builder.trace_accounting(username, acct_status_type, session_id, sent, started, "")
            result.response_time_ms = (time.perf_counter() - started) * 1000
            result.error = "超时；%s" % exc.detail
            result.code_name = "Timeout"
            result.extra["acct_session_id"] = session_id
            return result
        except RadiusError as exc:
            builder.remember_request(result, sent)
            builder.trace_accounting(username, acct_status_type, session_id, sent, started, "")
            result.response_time_ms = (time.perf_counter() - started) * 1000
            result.error = str(exc)
            result.extra["acct_session_id"] = session_id
            return result
        builder.remember_request(result, sent)
        result.response_time_ms = (time.perf_counter() - started) * 1000
        packet_obj = decode_packet(response)
        result.response_packet = packet_obj
        result.code = packet_obj.code
        result.code_name = packet_obj.code_name
        result.success = packet_obj.code == codes.ACCOUNTING_RESPONSE
        attribute_bytes = packet_obj.raw[20:] if len(packet_obj.raw) > 20 else b""
        result.authenticator_valid = auth_mod.verify_response_authenticator(
            packet_obj.code, packet_obj.identifier, packet_obj.length,
            sent.get("payload", packet)[4:20], attribute_bytes, secret,
            packet_obj.authenticator,
        )
        if not result.success:
            result.error = "未预期的响应类型：%s" % packet_obj.code_name
        result.extra["acct_session_id"] = session_id
        builder.trace_accounting(username, acct_status_type, session_id, sent, started,
                          result.code_name)
        return result
