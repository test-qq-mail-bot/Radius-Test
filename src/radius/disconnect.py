# -*- coding: utf-8 -*-
"""
Disconnect-Request 监听模块（RFC 5176）。

职责：
    1. 监听 UDP 3799，接收 RADIUS 服务器主动下发的 Disconnect-Request（DM）或 CoA-Request；
    2. 用共享密钥校验请求的 Request Authenticator；
    3. 回 Disconnect-ACK / CoA-ACK；
    4. 把校验通过的请求交给回调处理（标记会话掉线）。

背景（需求4）：
    管理员在 RADIUS 服务器上强制用户下线时，服务器会向 NAS 下发 DM-Request；
    NAS 回 DM-ACK 并随后发送 Accounting-Stop，服务器才会真正结束计费。
    本工具此前没有任何 3799 监听，导致该流程停在中途、服务器继续应答计费，
    于是「掉线率」「平均掉线时长」永远不会变化。

算法（RFC 5176 第 3 节）：
    DM-Request 的 Request Authenticator：
        MD5(Code + Identifier + Length + 16 个零字节 + 属性 + 共享密钥)
        与 RFC 2866 计费请求完全同式，故直接复用认证器模块。
    DM-ACK 的 Response Authenticator：
        MD5(Code + Identifier + Length + RequestAuth + 属性 + 共享密钥)
        与普通响应同式，同样复用。
    校验不通过的报文按 RFC 5176 要求「静默丢弃」。

部署约束：
    DM-Request 固定发往 NAS 的 UDP 3799。若本工具与 RADIUS 服务器部署在同一台机器，
    3799 通常已被服务器自身占用（Windows 上更具体的绑定优先），监听会绑定失败。
    这属于部署限制而非缺陷：模块会降级为 WARNING 并保持认证与计费功能不受影响。
"""

import asyncio
import hmac
import socket
from typing import Callable, List, Optional

from ..logging import logger
from . import attributes as attr_mod
from . import authenticator as auth_mod
from . import codes
from . import packet as packet_mod

# 承载 Disconnect-Request / CoA-Request 的标准端口（RFC 5176 第 3 节）
DISCONNECT_PORT = 3799
# 日志中展示的属性数量上限，避免超长属性刷屏
SUMMARY_ATTR_LIMIT = 20
# 日志中需要隐藏取值的属性：User-Password(2) / CHAP-Password(3) / Message-Authenticator(80)
MASKED_ATTR_IDS = (2, 3, 80)


def local_ipv4_candidates(target_host: str = "") -> List[str]:
    """
    返回本机可用于接收报文的 IPv4 地址列表（不含回环地址）。

    参数：
        target_host: 已配置的 RADIUS Server 地址。非空时优先用它推导本机出口地址：
            UDP connect 不产生实际报文，只是让系统按路由选定出口地址。

    返回：
        IPv4 地址列表，可能为空。
    """
    result: List[str] = []
    if target_host:
        probe = None
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect((target_host, 1812))
            result.append(probe.getsockname()[0])
        except OSError:
            pass
        finally:
            if probe is not None:
                probe.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in result and not ip.startswith("127."):
                result.append(ip)
    except OSError:
        pass
    return result


class DisconnectProtocol(asyncio.DatagramProtocol):
    """UDP 3799 数据报协议实现，把收到的数据报转交监听器处理。"""

    def __init__(self, listener: "DisconnectListener"):
        self._listener = listener

    def datagram_received(self, data: bytes, addr) -> None:
        """收到数据报。"""
        self._listener.handle(data, addr)

    def error_received(self, exc: Exception) -> None:
        """套接字层错误（不中断监听）。"""
        logger.warning("radius", "Disconnect 监听套接字异常", {"error": str(exc)})


class DisconnectListener:
    """
    Disconnect-Request 监听器。

    参数：
        port: 监听端口，默认 3799
        enabled: 是否启用（对应配置项 test.disconnect_listener.enabled）
        probe_host: 用于推导本机地址的已配置 Server 地址，可为空
    """

    def __init__(self, port: int = DISCONNECT_PORT, enabled: bool = True,
                 probe_host: str = ""):
        self.port = int(port or DISCONNECT_PORT)
        self.enabled = bool(enabled)
        self.probe_host = str(probe_host or "")
        self._transport = None
        self._bound_address = ""
        # 收到并校验通过后的回调：async def handler(session_id, username, peer, server_name)
        self._handler: Optional[Callable] = None
        # 共享密钥提供者：返回 [(server_name, secret), ...]
        self._secret_provider: Optional[Callable] = None
        # 运行统计，供自检脚本与排查使用
        self.stats = {"received": 0, "acked": 0, "rejected": 0, "ignored": 0}

    # ---------------- 装配 ----------------

    def set_handler(self, handler: Callable) -> None:
        """设置掉线回调（协程函数）。"""
        self._handler = handler

    def set_secret_provider(self, provider: Callable) -> None:
        """设置共享密钥提供者，返回 [(server_name, secret), ...]。"""
        self._secret_provider = provider

    @property
    def running(self) -> bool:
        """是否已成功绑定并监听。"""
        return self._transport is not None

    @property
    def bound_address(self) -> str:
        """已绑定的监听地址；未成功绑定为空串。"""
        return self._bound_address

    # ---------------- 生命周期 ----------------

    async def start(self) -> bool:
        """
        绑定并开始监听。

        返回：
            True 表示绑定成功；False 表示已停用或绑定失败（降级运行）。

        说明：
            依次尝试「0.0.0.0 -> 本机各网卡地址 -> 127.0.0.1」，
            全部失败只记录日志，不抛异常——认证与计费功能不受影响。
        """
        if not self.enabled:
            logger.info("radius", "Disconnect 监听已停用", {
                "config": "test.disconnect_listener.enabled",
            })
            return False

        candidates = ["0.0.0.0"]
        for ip in local_ipv4_candidates(self.probe_host):
            if ip not in candidates:
                candidates.append(ip)
        candidates.append("127.0.0.1")

        loop = asyncio.get_running_loop()
        last_error: Optional[Exception] = None
        for host in candidates:
            try:
                transport, _protocol = await loop.create_datagram_endpoint(
                    lambda: DisconnectProtocol(self), local_addr=(host, self.port))
            except OSError as exc:
                last_error = exc
                continue
            self._transport = transport
            self._bound_address = "%s:%d" % (host, self.port)
            logger.info("radius", "Disconnect 监听已启动", {
                "address": self._bound_address,
                "purpose": "接收 RADIUS 服务器主动下发的 Disconnect-Request",
            })
            if host == "0.0.0.0":
                logger.debug("radius", "Disconnect 监听使用通配地址", {
                    "note": "已绑定全部本地地址。注意：若本机同时运行 RADIUS 服务器，"
                            "发往本机具体 IP:3799 的 Disconnect-Request 会优先投递给服务器进程，"
                            "本监听收不到（实测 Windows 上具体地址绑定优先于通配地址）；"
                            "此时应把本工具部署到独立机器",
                })
            else:
                # 未能绑定全部地址：只有发往该地址的 Disconnect-Request 才收得到
                logger.warning("radius", "Disconnect 监听仅绑定了特定地址", {
                    "address": self._bound_address,
                    "tried": ",".join(candidates),
                    "hint": "服务端会把 Disconnect-Request 发往 NAS 地址（RFC 5176 固定 3799 端口）；"
                            "目标地址与绑定地址不一致时收不到",
                })
            return True

        logger.warning("radius", "Disconnect 监听启动失败，已降级运行（认证与计费不受影响）", {
            "port": self.port,
            "error": str(last_error),
            "tried": ",".join(candidates),
            "hint": "若本工具与 RADIUS 服务器部署在同一台机器，3799 通常已被服务器自身占用，"
                    "此时无法接收 Disconnect-Request；请把本工具部署到另一台机器后重试",
        })
        return False

    def stop(self) -> None:
        """停止监听并释放端口。"""
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("radius", "Disconnect 监听关闭异常", {"error": str(exc)})
            self._transport = None
        self._bound_address = ""

    # ---------------- 报文处理 ----------------

    def handle(self, data: bytes, addr) -> None:
        """
        处理一个收到的数据报。

        流程：解析 -> 校验 Request Authenticator -> 回 DM-ACK -> 触发掉线回调。
        校验失败按 RFC 5176 第 3 节静默丢弃（不回 NAK，避免被用作反射放大）。
        """
        peer = "%s:%s" % (addr[0], addr[1])
        self.stats["received"] += 1

        if len(data) < packet_mod.PACKET_HEADER_LENGTH:
            self.stats["ignored"] += 1
            logger.warning("radius", "Disconnect 报文过短，已忽略", {
                "peer": peer, "bytes": len(data)})
            return

        request = packet_mod.decode_packet(data)
        if request.code not in (codes.DISCONNECT_REQUEST, codes.COA_REQUEST):
            self.stats["ignored"] += 1
            logger.debug("radius", "3799 收到非 Disconnect/CoA 报文，已忽略", {
                "peer": peer, "code": "%s(%d)" % (request.code_name, request.code)})
            return

        # 校验与应答必须使用「收到的原始属性区字节」，避免重新编码引入差异
        attributes_bytes = request.raw[packet_mod.PACKET_HEADER_LENGTH:request.length]
        server_name, secret = self._match_secret(request, attributes_bytes)
        if secret is None:
            self.stats["rejected"] += 1
            logger.warning("radius", "Disconnect 报文认证器校验失败，按 RFC 5176 静默丢弃", {
                "peer": peer,
                "code": request.code_name,
                "identifier": request.identifier,
                "attrs": self._summarize(request),
            })
            return

        session_id = self._attr_text(request, codes.ATTR_ACCT_SESSION_ID)
        username = self._attr_text(request, codes.ATTR_USER_NAME)
        logger.info("radius", "收到 Disconnect-Request", {
            "peer": peer,
            "server": server_name or "-",
            "code": request.code_name,
            "identifier": request.identifier,
            "username": username or "-",
            "session_id": session_id or "-",
            "attrs": self._summarize(request),
        })

        self._send_ack(request, addr, secret, session_id)

        if self._handler is None:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._handler(session_id, username, peer, server_name))
        except RuntimeError:
            logger.warning("radius", "事件循环不可用，未触发掉线标记", {"peer": peer})

    def _match_secret(self, request, attributes_bytes: bytes):
        """
        逐个候选密钥校验请求认证器。

        返回：
            (server_name, secret_bytes)；全部不匹配时返回 ("", None)。
        """
        for name, secret in self._secret_candidates():
            expected = auth_mod.compute_accounting_request_authenticator(
                request.code, request.identifier, request.length,
                attributes_bytes, secret)
            if hmac.compare_digest(expected, request.authenticator):
                return name, secret
        return "", None

    def _secret_candidates(self) -> list:
        """返回 [(server_name, secret_bytes), ...]，跳过空密钥。"""
        if self._secret_provider is None:
            return []
        try:
            items = self._secret_provider() or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("radius", "读取共享密钥失败", {"error": str(exc)})
            return []
        result = []
        for name, secret in items:
            if not secret:
                continue
            if isinstance(secret, str):
                secret = secret.encode("utf-8")
            result.append((name, secret))
        return result

    def _send_ack(self, request, addr, secret: bytes, session_id: str) -> None:
        """回复 DM-ACK / CoA-ACK，回显会话 ID 便于服务端匹配。"""
        response_attrs = []
        if session_id:
            response_attrs.append((codes.ATTR_ACCT_SESSION_ID, session_id.encode("utf-8")))
        ack_bytes = attr_mod.encode_attributes(response_attrs)
        ack_code = (codes.COA_ACK if request.code == codes.COA_REQUEST
                    else codes.DISCONNECT_ACK)
        length = packet_mod.PACKET_HEADER_LENGTH + len(ack_bytes)
        response_auth = auth_mod.compute_response_authenticator(
            ack_code, request.identifier, length, request.authenticator, ack_bytes, secret)
        payload = packet_mod.encode_packet(
            ack_code, request.identifier, response_auth, ack_bytes)
        try:
            if self._transport is not None:
                self._transport.sendto(payload, addr)
            self.stats["acked"] += 1
            logger.info("radius", "已回复 Disconnect-ACK", {
                "peer": "%s:%s" % (addr[0], addr[1]),
                "code": codes.packet_code_name(ack_code),
                "identifier": request.identifier,
                "session_id": session_id or "-",
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("radius", "Disconnect-ACK 发送失败", {
                "peer": "%s:%s" % (addr[0], addr[1]), "error": str(exc)})

    @staticmethod
    def _attr_text(request, attr_id: int) -> str:
        """取首个标准属性的文本值（监听侧不做 Dictionary 匹配，直接用原始字节解码）。"""
        for attr in request.attributes:
            if attr.attr_id == attr_id and attr.vendor_id is None:
                return attr.raw.decode("utf-8", "replace").strip()
        return ""

    @staticmethod
    def _summarize(request) -> str:
        """输出属性清单（属性号=值），供排查服务端究竟下发了哪些字段。"""
        items = []
        for attr in request.attributes[:SUMMARY_ATTR_LIMIT]:
            if attr.vendor_id is not None:
                text = attr.raw.decode("utf-8", "replace").strip() or attr.raw.hex()
                items.append("vsa-%d-%d=%s" % (attr.vendor_id, attr.attr_id,
                                               text.replace(";", ",")))
                continue
            if attr.attr_id in MASKED_ATTR_IDS:
                items.append("%d=<已隐藏>" % attr.attr_id)
                continue
            text = attr.raw.decode("utf-8", "replace").strip() or attr.raw.hex()
            items.append("%d=%s" % (attr.attr_id, text.replace(";", ",").replace("\n", " ")))
        if len(request.attributes) > SUMMARY_ATTR_LIMIT:
            items.append("...(共 %d 个属性)" % len(request.attributes))
        return ";".join(items) or "无"
