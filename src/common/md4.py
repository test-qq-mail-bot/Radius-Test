# -*- coding: utf-8 -*-
"""
MD4 哈希算法（纯 Python 实现）。

存在原因（项目书 3.2）：
    MS-CHAP v1/v2 计算 NtPasswordHash 时必须使用 MD4。
    cryptography 45.x 的 hazmat 摘要清单中不含 MD4，
    OpenSSL 3.x 也将 MD4 移入 Legacy Provider，
    因此本模块独立实现 MD4，不依赖系统 OpenSSL。

参考：RFC 1320 The MD4 Message-Digest Algorithm
"""

import struct

_MASK32 = 0xFFFFFFFF

# 每轮使用的循环左移位数
_SHIFT_R1 = (3, 7, 11, 19)
_SHIFT_R2 = (3, 5, 9, 13)
_SHIFT_R3 = (3, 9, 11, 15)

# 第二轮与第三轮的消息字索引顺序
_ORDER_R2 = (0, 4, 8, 12, 1, 5, 9, 13, 2, 6, 10, 14, 3, 7, 11, 15)
_ORDER_R3 = (0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15)

# 轮常量
_K_R2 = 0x5A827999
_K_R3 = 0x6ED9EBA1


def _rotl(value: int, shift: int) -> int:
    """32 位循环左移。"""
    value &= _MASK32
    return ((value << shift) | (value >> (32 - shift))) & _MASK32


def _f(x: int, y: int, z: int) -> int:
    """第一轮逻辑函数 F(X,Y,Z) = (X AND Y) OR (NOT X AND Z)。"""
    return (x & y) | (~x & z)


def _g(x: int, y: int, z: int) -> int:
    """第二轮逻辑函数 G(X,Y,Z) = (X AND Y) OR (X AND Z) OR (Y AND Z)。"""
    return (x & y) | (x & z) | (y & z)


def _h(x: int, y: int, z: int) -> int:
    """第三轮逻辑函数 H(X,Y,Z) = X XOR Y XOR Z。"""
    return x ^ y ^ z


def _pad(data: bytes, total_length: int = None) -> bytes:
    """
    MD4 填充。

    规则：追加 0x80，填充 0x00 至长度对 64 取模等于 56，
    最后追加 8 字节小端比特长度。

    参数：
        data: 剩余未满 64 字节的数据
        total_length: 全部已输入数据的字节数（跨 update 调用累计），
                      未提供时按 len(data) 计算。
    """
    if total_length is None:
        total_length = len(data)
    bit_len = (total_length * 8) & 0xFFFFFFFFFFFFFFFF
    padded = bytearray(data)
    padded.append(0x80)
    while len(padded) % 64 != 56:
        padded.append(0x00)
    padded += struct.pack("<Q", bit_len)
    return bytes(padded)


class MD4:
    """MD4 哈希计算器，接口模仿 hashlib。"""

    block_size = 64
    digest_size = 16
    name = "md4"

    def __init__(self, data: bytes = b""):
        # 初始链式变量（RFC 1320 第 3.3 节）
        self._a = 0x67452301
        self._b = 0xEFCDAB89
        self._c = 0x98BADCFE
        self._d = 0x10325476
        self._buffer = b""
        self._length = 0
        if data:
            self.update(data)

    def copy(self) -> "MD4":
        """返回当前状态的副本。"""
        clone = MD4()
        clone._a = self._a
        clone._b = self._b
        clone._c = self._c
        clone._d = self._d
        clone._buffer = self._buffer
        clone._length = self._length
        return clone

    def update(self, data: bytes) -> None:
        """追加待计算数据。"""
        self._length += len(data)
        self._buffer += data
        while len(self._buffer) >= 64:
            block = self._buffer[:64]
            self._buffer = self._buffer[64:]
            self._compress(block)

    def _compress(self, block: bytes) -> None:
        """处理单个 64 字节分组。"""
        x = struct.unpack("<16I", block)
        a, b, c, d = self._a, self._b, self._c, self._d

        # 第一轮：16 步，不使用常量
        for i in range(16):
            k = i
            s = _SHIFT_R1[i % 4]
            if i % 4 == 0:
                a = _rotl(a + _f(b, c, d) + x[k], s)
            elif i % 4 == 1:
                d = _rotl(d + _f(a, b, c) + x[k], s)
            elif i % 4 == 2:
                c = _rotl(c + _f(d, a, b) + x[k], s)
            else:
                b = _rotl(b + _f(c, d, a) + x[k], s)

        # 第二轮：16 步，使用常量 0x5A827999
        for i in range(16):
            k = _ORDER_R2[i]
            s = _SHIFT_R2[i % 4]
            if i % 4 == 0:
                a = _rotl(a + _g(b, c, d) + x[k] + _K_R2, s)
            elif i % 4 == 1:
                d = _rotl(d + _g(a, b, c) + x[k] + _K_R2, s)
            elif i % 4 == 2:
                c = _rotl(c + _g(d, a, b) + x[k] + _K_R2, s)
            else:
                b = _rotl(b + _g(c, d, a) + x[k] + _K_R2, s)

        # 第三轮：16 步，使用常量 0x6ED9EBA1
        for i in range(16):
            k = _ORDER_R3[i]
            s = _SHIFT_R3[i % 4]
            if i % 4 == 0:
                a = _rotl(a + _h(b, c, d) + x[k] + _K_R3, s)
            elif i % 4 == 1:
                d = _rotl(d + _h(a, b, c) + x[k] + _K_R3, s)
            elif i % 4 == 2:
                c = _rotl(c + _h(d, a, b) + x[k] + _K_R3, s)
            else:
                b = _rotl(b + _h(c, d, a) + x[k] + _K_R3, s)

        self._a = (self._a + a) & _MASK32
        self._b = (self._b + b) & _MASK32
        self._c = (self._c + c) & _MASK32
        self._d = (self._d + d) & _MASK32

    def digest(self) -> bytes:
        """返回 16 字节摘要。"""
        state = self.copy()
        # 必须用累计总长度计算填充中的长度字段，而不是剩余缓冲区长度
        tail = _pad(state._buffer, state._length)
        for offset in range(0, len(tail), 64):
            state._compress(tail[offset:offset + 64])
        return struct.pack("<4I", state._a, state._b, state._c, state._d)

    def hexdigest(self) -> str:
        """返回 32 位十六进制摘要。"""
        return self.digest().hex()


def md4(data: bytes) -> bytes:
    """一次性计算 MD4 摘要，返回 16 字节。"""
    return MD4(data).digest()


def md4_hex(data: bytes) -> str:
    """一次性计算 MD4 摘要，返回十六进制字符串。"""
    return MD4(data).hexdigest()
