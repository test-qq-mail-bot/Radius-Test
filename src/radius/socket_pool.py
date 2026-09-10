# -*- coding: utf-8 -*-
"""
UDP 源端口 Socket 池模块。

存在原因（关键工程约束）：
    RADIUS Identifier 字段只有 1 字节，即 0~255。
    依据 RFC 2865 第 5 节，服务器通过 (源 IP + 源 UDP 端口 + Identifier) 匹配请求，
    因此**单个源端口最多只能有 256 个在途请求**。
    项目书要求 max_concurrency 默认 10000，单 Socket 无法满足，
    必须使用多个源端口组成 Socket 池：
        10000 / 256 ≈ 40 个源端口

设计：
    1. 每个 Slot 占用一个本地 UDP 源端口，独立维护 256 个 Identifier；
    2. Slot 按需惰性创建，避免浪费本机临时端口；
    3. 请求发出后在 Slot 内登记 Future，收到响应时按 Identifier 唤醒；
    4. 支持超时重传与取消。

参考：
    RFC 2865 Section 5
    IETF draft-dekok-radext-request-authenticator
"""

import asyncio
import socket
import time
from typing import Dict, Optional

from ..common.errors import RadiusError, RadiusTimeout
from ..logging import logger
from . import trace

# 每个源端口可用的 Identifier 数量（1 字节）
IDENTIFIERS_PER_SLOT = 256
# Socket 池上限，避免耗尽本机临时端口
MAX_SLOTS = 256
# 平台临时端口数量参考值（仅用于日志提示，不做硬限制）
WINDOWS_EPHEMERAL_PORTS = 16384
LINUX_EPHEMERAL_PORTS = 28232


class _SlotProtocol(asyncio.DatagramProtocol):
    """单个 UDP Socket 的 asyncio 协议实现。"""

    def __init__(self, slot: "SocketSlot"):
        self.slot = slot
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Socket 就绪回调。"""
        self.transport = transport  # type: ignore[assignment]
        self.slot.mark_ready(transport)  # type: ignore[arg-type]

    def datagram_received(self, data: bytes, addr) -> None:
        """收到数据报回调。"""
        self.slot.on_datagram(data, addr)

    def error_received(self, exc: Exception) -> None:
        """Socket 错误回调。"""
        self.slot.on_error(exc)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        """Socket 关闭回调。"""
        self.slot.mark_closed()


class SocketSlot:
    """
    UDP Socket 池中的单个槽位。

    每个槽位占用一个本地源端口，独立管理 256 个 Identifier 的分配与回收。
    """

    def __init__(self, index: int, family: int):
        self.index = index
        self.family = family
        self.transport: Optional[asyncio.DatagramTransport] = None
        self._ready = asyncio.Event()
        self._pending: Dict[int, asyncio.Future] = {}
        self._free_ids: list = list(range(IDENTIFIERS_PER_SLOT))
        self._next_id = 0
        self._closed = False
        self.in_flight = 0

    def mark_ready(self, transport: asyncio.DatagramTransport) -> None:
        """Socket 创建完成。"""
        self.transport = transport
        self._ready.set()

    def mark_closed(self) -> None:
        """Socket 已关闭，唤醒全部等待中的请求。"""
        self._closed = True
        error = RadiusError("UDP Socket 已关闭", "slot=%d" % self.index)
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    def on_error(self, exc: Exception) -> None:
        """Socket 层错误。"""
        logger.warning("socket_pool", "UDP Socket 错误", {
            "slot": self.index,
            "error": str(exc),
        })

    def on_datagram(self, data: bytes, addr) -> None:
        """
        收到响应数据报。

        按 Identifier 查找等待中的请求并唤醒；找不到时丢弃（重复或过期响应）。
        """
        if len(data) < 2:
            return
        identifier = data[1]
        future = self._pending.get(identifier)
        if future is not None and not future.done():
            future.set_result((data, addr))

    async def wait_ready(self, timeout: float = 5.0) -> None:
        """等待 Socket 创建完成。"""
        if self._ready.is_set():
            return
        await asyncio.wait_for(self._ready.wait(), timeout)

    def has_free_identifier(self) -> bool:
        """
        判断本槽位是否存在空闲 Identifier（只查询，不消耗）。

        说明：
            选槽位与分配 Identifier 必须分离。若用 acquire_identifier() 的
            返回值来探测空位，探测本身就会消耗一个 Identifier，
            造成每次请求泄漏一个，最终池被耗尽。
        """
        return (not self._closed) and bool(self._free_ids)

    def acquire_identifier(self) -> Optional[int]:
        """
        申请一个空闲 Identifier。

        返回：
            Identifier（0~255）；全部占用时返回 None。
        """
        if self._free_ids:
            return self._free_ids.pop()
        return None

    def release_identifier(self, identifier: Optional[int]) -> None:
        """
        归还 Identifier。

        说明：
            重复归还会导致同一 Identifier 被两个并发请求同时使用，
            进而出现响应串包，因此归还前必须查重。
        """
        if identifier is None:
            return
        if identifier not in self._free_ids:
            self._free_ids.append(identifier)

    def send(self, data: bytes, host: str, port: int, identifier: int) -> None:
        """通过本槽位发送数据报。"""
        if self.transport is None or self._closed:
            raise RadiusError("UDP Socket 不可用", "slot=%d" % self.index)
        if self.family == socket.AF_INET6:
            self.transport.sendto(data, (host, port, 0, 0))
        else:
            self.transport.sendto(data, (host, port))

    def register(self, identifier: int) -> asyncio.Future:
        """登记等待中的请求。"""
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending[identifier] = future
        self.in_flight = len(self._pending)
        return future

    def unregister(self, identifier: int) -> None:
        """注销等待中的请求。"""
        self._pending.pop(identifier, None)
        self.in_flight = len(self._pending)

    def close(self) -> None:
        """关闭槽位。"""
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass
            self.transport = None
        self._closed = True


class UdpSocketPool:
    """
    UDP 源端口 Socket 池。

    对外提供 send_request 协程，自动完成：
        槽位选择 -> Identifier 申请 -> 发送 -> 等待响应 -> 超时重传 -> 归还资源
    """

    def __init__(self, family: int = socket.AF_INET, max_slots: int = MAX_SLOTS,
                 source_address: str = ""):
        self.family = family
        self.max_slots = max(1, min(max_slots, MAX_SLOTS))
        self.source_address = (source_address or "").strip()
        self._slots: list = []
        self._lock = asyncio.Lock()
        self._round_robin = 0

    @property
    def slot_count(self) -> int:
        """当前已创建的槽位数量。"""
        return len(self._slots)

    @property
    def capacity(self) -> int:
        """当前理论最大在途请求数。"""
        return len(self._slots) * IDENTIFIERS_PER_SLOT

    async def _create_slot(self) -> SocketSlot:
        """创建一个新的 UDP 槽位。"""
        loop = asyncio.get_event_loop()
        slot = SocketSlot(len(self._slots), self.family)
        local_addr = (self.source_address, 0) if self.source_address \
            else (("::", 0) if self.family == socket.AF_INET6 else ("0.0.0.0", 0))
        await loop.create_datagram_endpoint(
            lambda: _SlotProtocol(slot),
            family=self.family,
            local_addr=local_addr,
        )
        await slot.wait_ready()
        self._slots.append(slot)
        logger.debug("socket_pool", "已创建 UDP Socket 槽位", {
            "slot": slot.index,
            "family": "IPv6" if self.family == socket.AF_INET6 else "IPv4",
            "capacity": self.capacity,
        })
        return slot

    async def _acquire_slot(self) -> SocketSlot:
        """
        获取一个可用槽位。

        优先复用已有槽位的空闲 Identifier；全部占满且未达上限时新建槽位；
        达到上限时等待任意一个槽位释放。
        """
        async with self._lock:
            for _ in range(len(self._slots)):
                slot = self._slots[self._round_robin % len(self._slots)]
                self._round_robin += 1
                # 只探测是否有空闲 Identifier，不在此处消耗：
                # 实际分配由 send_request 紧接着调用 acquire_identifier 完成，
                # 两次调用之间没有 await，因此不会被其他协程插入，分配是原子的。
                if slot.has_free_identifier():
                    return slot
            if len(self._slots) < self.max_slots:
                return await self._create_slot()
        # 池已满，轮询等待空闲 Identifier
        for _ in range(200):
            for slot in self._slots:
                if slot.has_free_identifier():
                    return slot
            await asyncio.sleep(0.005)
        raise RadiusError("UDP Socket 池已满，无空闲 Identifier", "槽位数=%d" % len(self._slots))

    async def send_request(
        self,
        data: bytes,
        host: str,
        port: int,
        timeout: float = 5.0,
        retry_count: int = 3,
        signer=None,
        on_sent=None,
    ) -> bytes:
        """
        发送 RADIUS 请求并等待响应。

        参数：
            data: 完整请求报文字节串（Identifier 会被本方法覆写）
            host: 目标地址
            port: 目标端口
            timeout: 单次等待超时（秒）
            retry_count: 最大尝试次数（含首次）
            signer: 可选回调 signer(payload) -> payload。
                在 Identifier 覆写之后调用，用于重算依赖 Identifier 的字段
                （Accounting-Request 的 Request Authenticator 必须如此，
                 见 RFC 2866 3）。
            on_sent: 可选回调 on_sent(payload)，在报文真正发出后调用，
                传入最终字节串，便于上屏/落库展示真实报文。

        返回：
            响应报文字节串。

        异常：
            RadiusTimeout: 重试次数用尽仍未收到响应。
        """
        slot = await self._acquire_slot()
        identifier = slot.acquire_identifier()
        if identifier is None:
            # 理论上不会走到这里：_acquire_slot 只返回拥有空闲 Identifier 的槽位，
            # 且两次调用之间没有 await，不会被其他协程抢占。
            raise RadiusError("无法申请 Identifier", "slot=%d" % slot.index)
        packet = bytearray(data)
        packet[1] = identifier
        payload = bytes(packet)
        if signer is not None:
            payload = signer(payload)
        if on_sent is not None:
            on_sent(payload)
        future = slot.register(identifier)
        try:
            attempt = 0
            last_error = ""
            while attempt < max(1, retry_count):
                attempt += 1
                started = time.perf_counter()
                try:
                    slot.send(payload, host, port, identifier)
                    response, _addr = await asyncio.wait_for(asyncio.shield(future), timeout)
                    trace.record_send(
                        module="radius", host=host, port=port, identifier=identifier,
                        payload=payload, response=response,
                        elapsed_ms=(time.perf_counter() - started) * 1000,
                        attempt=attempt, retry_count=retry_count, slot=slot.index,
                    )
                    return response
                except asyncio.TimeoutError:
                    last_error = "第 %d 次尝试超时（%.1f 秒）" % (attempt, timeout)
                    trace.record_timeout(
                        module="radius", host=host, port=port, identifier=identifier,
                        payload=payload, elapsed_ms=(time.perf_counter() - started) * 1000,
                        attempt=attempt, retry_count=retry_count, slot=slot.index,
                    )
                    if future.done():
                        break
                    continue
            raise RadiusTimeout(
                "RADIUS 请求超时",
                "目标=%s:%s；尝试=%d 次；%s" % (host, port, attempt, last_error),
            )
        finally:
            slot.unregister(identifier)
            slot.release_identifier(identifier)

    async def close(self) -> None:
        """关闭全部槽位。"""
        for slot in self._slots:
            slot.close()
        self._slots.clear()


class SocketPoolManager:
    """
    Socket 池管理器。

    按地址族分别维护 Socket 池，对外屏蔽 IPv4 / IPv6 差异。
    """

    def __init__(self, max_concurrency: int = 10000):
        # 需要的槽位数 = ceil(max_concurrency / 256)
        needed = -(-int(max_concurrency) // IDENTIFIERS_PER_SLOT)
        self.max_slots = max(1, min(needed, MAX_SLOTS))
        self._pools: Dict[int, UdpSocketPool] = {}
        self._lock = asyncio.Lock()

    def _family_of(self, host: str) -> int:
        """根据目标地址判断地址族。"""
        return socket.AF_INET6 if ":" in host else socket.AF_INET

    async def get_pool(self, host: str, source_address: str = "") -> UdpSocketPool:
        """获取目标地址对应的 Socket 池（不存在则创建）。

        池以 (地址族, 源地址) 为键：不同源地址需要绑定到不同 Socket，
        因此各自维护独立池；源地址与目标地址族不一致时自动忽略源地址。
        """
        family = self._family_of(host)
        src = (source_address or "").strip()
        if src and self._family_of(src) != family:
            logger.warning("socket_pool", "源地址与目标地址族不一致，已忽略源地址", {
                "source": src, "host": host,
            })
            src = ""
        key = (family, src)
        if key in self._pools:
            return self._pools[key]
        async with self._lock:
            if key not in self._pools:
                self._pools[key] = UdpSocketPool(
                    family=family, max_slots=self.max_slots, source_address=src)
            return self._pools[key]

    async def send_request(
        self,
        data: bytes,
        host: str,
        port: int,
        timeout: float = 5.0,
        retry_count: int = 3,
        source_address: str = "",
        signer=None,
        on_sent=None,
    ) -> bytes:
        """发送 RADIUS 请求并等待响应。"""
        pool = await self.get_pool(host, source_address)
        return await pool.send_request(data, host, port, timeout, retry_count,
                                       signer=signer, on_sent=on_sent)

    def stats(self) -> dict:
        """返回 Socket 池统计信息，供系统信息接口使用。"""
        result = {}
        for family, pool in self._pools.items():
            key = "ipv6" if family == socket.AF_INET6 else "ipv4"
            result[key] = {
                "slots": pool.slot_count,
                "capacity": pool.capacity,
                "max_slots": pool.max_slots,
            }
        result["max_slots_configured"] = self.max_slots
        result["identifiers_per_slot"] = IDENTIFIERS_PER_SLOT
        return result

    async def close(self) -> None:
        """关闭全部 Socket 池。"""
        for pool in self._pools.values():
            await pool.close()
        self._pools.clear()
