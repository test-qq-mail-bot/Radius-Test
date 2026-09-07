# -*- coding: utf-8 -*-
"""
DES 分组密码（纯 Python 实现，ECB 模式）。

存在原因（项目书 3.2）：
    MS-CHAP v1/v2 计算 NT-Response / LM-Response 时必须使用单 DES（56 位有效密钥）。
    cryptography 45.x 的对称算法清单中只有 TripleDES，没有单 DES；
    OpenSSL 3.x 也将单 DES 移入 Legacy Provider。
    因此本模块独立实现 DES，不依赖系统 OpenSSL。

参考：FIPS 46-3 Data Encryption Standard

性能说明：
    纯 Python DES 单次加密约需数十微秒至百微秒级，
    因此 DESKey 会预计算并缓存轮密钥，高并发场景下由上层按密码哈希复用。
"""

# ---------- 置换表（标准 1-based 位编号） ----------

# 初始置换 IP（64 -> 64）
_IP = (
    58, 50, 42, 34, 26, 18, 10, 2, 60, 52, 44, 36, 28, 20, 12, 4,
    62, 54, 46, 38, 30, 22, 14, 6, 64, 56, 48, 40, 32, 24, 16, 8,
    57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3,
    61, 53, 45, 37, 29, 21, 13, 5, 63, 55, 47, 39, 31, 23, 15, 7,
)

# 逆初始置换 FP = IP^-1（64 -> 64）
_FP = (
    40, 8, 48, 16, 56, 24, 64, 32, 39, 7, 47, 15, 55, 23, 63, 31,
    38, 6, 46, 14, 54, 22, 62, 30, 37, 5, 45, 13, 53, 21, 61, 29,
    36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27,
    34, 2, 42, 10, 50, 18, 58, 26, 33, 1, 41, 9, 49, 17, 57, 25,
)

# 扩展置换 E（32 -> 48）
_E = (
    32, 1, 2, 3, 4, 5, 4, 5, 6, 7, 8, 9, 8, 9, 10, 11,
    12, 13, 12, 13, 14, 15, 16, 17, 16, 17, 18, 19, 20, 21, 20, 21,
    22, 23, 24, 25, 24, 25, 26, 27, 28, 29, 28, 29, 30, 31, 32, 1,
)

# P 置换（32 -> 32）
_P = (
    16, 7, 20, 21, 29, 12, 28, 17, 1, 15, 23, 26, 5, 18, 31, 10,
    2, 8, 24, 14, 32, 27, 3, 9, 19, 13, 30, 6, 22, 11, 4, 25,
)

# 密钥置换 PC1（64 -> 56）
_PC1 = (
    57, 49, 41, 33, 25, 17, 9, 1, 58, 50, 42, 34, 26, 18,
    10, 2, 59, 51, 43, 35, 27, 19, 11, 3, 60, 52, 44, 36,
    63, 55, 47, 39, 31, 23, 15, 7, 62, 54, 46, 38, 30, 22,
    14, 6, 61, 53, 45, 37, 29, 21, 13, 5, 28, 20, 12, 4,
)

# 密钥压缩置换 PC2（56 -> 48）
_PC2 = (
    14, 17, 11, 24, 1, 5, 3, 28, 15, 6, 21, 10,
    23, 19, 12, 4, 26, 8, 16, 7, 27, 20, 13, 2,
    41, 52, 31, 37, 47, 55, 30, 40, 51, 45, 33, 48,
    44, 49, 39, 56, 34, 53, 46, 42, 50, 36, 29, 32,
)

# 每轮循环左移位数
_SHIFTS = (1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1)

# S 盒，8 个，每个 64 项
_SBOXES = (
    (14, 4, 13, 1, 2, 15, 11, 8, 3, 10, 6, 12, 5, 9, 0, 7,
     0, 15, 7, 4, 14, 2, 13, 1, 10, 6, 12, 11, 9, 5, 3, 8,
     4, 1, 14, 8, 13, 6, 2, 11, 15, 12, 9, 7, 3, 10, 5, 0,
     15, 12, 8, 2, 4, 9, 1, 7, 5, 11, 3, 14, 10, 0, 6, 13),
    (15, 1, 8, 14, 6, 11, 3, 4, 9, 7, 2, 13, 12, 0, 5, 10,
     3, 13, 4, 7, 15, 2, 8, 14, 12, 0, 1, 10, 6, 9, 11, 5,
     0, 14, 7, 11, 10, 4, 13, 1, 5, 8, 12, 6, 9, 3, 2, 15,
     13, 8, 10, 1, 3, 15, 4, 2, 11, 6, 7, 12, 0, 5, 14, 9),
    (10, 0, 9, 14, 6, 3, 15, 5, 1, 13, 12, 7, 11, 4, 2, 8,
     13, 7, 0, 9, 3, 4, 6, 10, 2, 8, 5, 14, 12, 11, 15, 1,
     13, 6, 4, 9, 8, 15, 3, 0, 11, 1, 2, 12, 5, 10, 14, 7,
     1, 10, 13, 0, 6, 9, 8, 7, 4, 15, 14, 3, 11, 5, 2, 12),
    (7, 13, 14, 3, 0, 6, 9, 10, 1, 2, 8, 5, 11, 12, 4, 15,
     13, 8, 11, 5, 6, 15, 0, 3, 4, 7, 2, 12, 1, 10, 14, 9,
     10, 6, 9, 0, 12, 11, 7, 13, 15, 1, 3, 14, 5, 2, 8, 4,
     3, 15, 0, 6, 10, 1, 13, 8, 9, 4, 5, 11, 12, 7, 2, 14),
    (2, 12, 4, 1, 7, 10, 11, 6, 8, 5, 3, 15, 13, 0, 14, 9,
     14, 11, 2, 12, 4, 7, 13, 1, 5, 0, 15, 10, 3, 9, 8, 6,
     4, 2, 1, 11, 10, 13, 7, 8, 15, 9, 12, 5, 6, 3, 0, 14,
     11, 8, 12, 7, 1, 14, 2, 13, 6, 15, 0, 9, 10, 4, 5, 3),
    (12, 1, 10, 15, 9, 2, 6, 8, 0, 13, 3, 4, 14, 7, 5, 11,
     10, 15, 4, 2, 7, 12, 9, 5, 6, 1, 13, 14, 0, 11, 3, 8,
     9, 14, 15, 5, 2, 8, 12, 3, 7, 0, 4, 10, 1, 13, 11, 6,
     4, 3, 2, 12, 9, 5, 15, 10, 11, 14, 1, 7, 6, 0, 8, 13),
    (4, 11, 2, 14, 15, 0, 8, 13, 3, 12, 9, 7, 5, 10, 6, 1,
     13, 0, 11, 7, 4, 9, 1, 10, 14, 3, 5, 12, 2, 15, 8, 6,
     1, 4, 11, 13, 12, 3, 7, 14, 10, 15, 6, 8, 0, 5, 9, 2,
     6, 11, 13, 8, 1, 4, 10, 7, 9, 5, 0, 15, 14, 2, 3, 12),
    (13, 2, 8, 4, 6, 15, 11, 1, 10, 9, 3, 14, 5, 0, 12, 7,
     1, 15, 13, 8, 10, 3, 7, 4, 12, 5, 6, 11, 0, 14, 9, 2,
     7, 11, 4, 1, 9, 12, 14, 2, 0, 6, 10, 13, 15, 3, 5, 8,
     2, 1, 14, 7, 4, 10, 8, 13, 15, 12, 9, 0, 3, 5, 6, 11),
)

# 预计算：把 1-based 位编号转换为「在 width 位整数中的右移量」
# 位编号规则：最高位为第 1 位；width 位整数中第 p 位对应 (value >> (width - p)) & 1
_IP_IDX = tuple(64 - v for v in _IP)
_FP_IDX = tuple(64 - v for v in _FP)
_E_IDX = tuple(32 - v for v in _E)
_P_IDX = tuple(32 - v for v in _P)
_PC1_IDX = tuple(64 - v for v in _PC1)
_PC2_IDX = tuple(56 - v for v in _PC2)


def _permute(value: int, width: int, index_table) -> int:
    """
    按置换表重排位。

    参数：
        value: 输入整数
        width: 输入位宽
        index_table: 每项为右移量，取值 = width - 位编号

    返回：
        置换后的整数，位宽等于 len(index_table)。
    """
    result = 0
    for shift in index_table:
        result = (result << 1) | ((value >> shift) & 1)
    return result


class DESKey:
    """
    DES 密钥对象，预先计算 16 个轮密钥。

    使用方式：
        key = DESKey(key8bytes)
        out = key.encrypt_block(block8bytes)

    说明：
        MS-CHAP 场景中同一密码的轮密钥完全相同，
        上层可以按密码哈希缓存 DESKey 实例以显著提升性能。
    """

    __slots__ = ("_subkeys", "_subkeys_rev")

    def __init__(self, key: bytes):
        if len(key) != 8:
            raise ValueError("DES 密钥长度必须是 8 字节，实际=%d" % len(key))
        k = int.from_bytes(key, "big")
        # PC1 得到 56 位密钥
        k56 = _permute(k, 64, _PC1_IDX)
        # 拆分为两个 28 位半密钥
        mask28 = 0x0FFFFFFF
        c = (k56 >> 28) & mask28
        d = k56 & mask28
        subkeys = []
        for shift in _SHIFTS:
            c = ((c << shift) | (c >> (28 - shift))) & mask28
            d = ((d << shift) | (d >> (28 - shift))) & mask28
            combined = (c << 28) | d
            subkeys.append(_permute(combined, 56, _PC2_IDX))
        self._subkeys = tuple(subkeys)
        self._subkeys_rev = tuple(reversed(subkeys))

    def _feistel(self, block: int) -> int:
        """单轮 Feistel 函数 f(R, K)。"""
        # 32 位 -> 48 位扩展
        expanded = _permute(block, 32, _E_IDX)
        return expanded

    def _round(self, r: int, subkey: int) -> int:
        """计算单轮输出：P(S(E(R) XOR K))，返回 32 位。"""
        expanded = _permute(r, 32, _E_IDX) ^ subkey
        out = 0
        pos = 42
        for sbox in _SBOXES:
            # 每次取 6 位：第 1、6 位组成行号，中间 4 位组成列号
            chunk = (expanded >> pos) & 0x3F
            pos -= 6
            row = ((chunk & 0x20) >> 4) | (chunk & 0x01)
            col = (chunk >> 1) & 0x0F
            out = (out << 4) | sbox[row * 16 + col]
        return _permute(out, 32, _P_IDX)

    def encrypt_block(self, block: bytes) -> bytes:
        """加密单个 8 字节分组，返回 8 字节密文。"""
        value = int.from_bytes(block, "big")
        value = _permute(value, 64, _IP_IDX)
        mask32 = 0xFFFFFFFF
        left = (value >> 32) & mask32
        right = value & mask32
        for subkey in self._subkeys:
            left, right = right, left ^ self._round(right, subkey)
        pre_output = ((right << 32) | left) & 0xFFFFFFFFFFFFFFFF
        return _permute(pre_output, 64, _FP_IDX).to_bytes(8, "big")

    def decrypt_block(self, block: bytes) -> bytes:
        """解密单个 8 字节分组，返回 8 字节明文。"""
        value = int.from_bytes(block, "big")
        value = _permute(value, 64, _IP_IDX)
        mask32 = 0xFFFFFFFF
        left = (value >> 32) & mask32
        right = value & mask32
        for subkey in self._subkeys_rev:
            left, right = right, left ^ self._round(right, subkey)
        pre_output = ((right << 32) | left) & 0xFFFFFFFFFFFFFFFF
        return _permute(pre_output, 64, _FP_IDX).to_bytes(8, "big")


def des_ecb_encrypt(key: bytes, data: bytes) -> bytes:
    """
    DES-ECB 加密。

    参数：
        key: 8 字节密钥
        data: 长度必须是 8 的整数倍

    返回：
        密文，长度与输入一致。
    """
    if len(data) % 8 != 0:
        raise ValueError("DES-ECB 输入长度必须是 8 的整数倍，实际=%d" % len(data))
    des_key = DESKey(key)
    out = bytearray()
    for offset in range(0, len(data), 8):
        out += des_key.encrypt_block(data[offset:offset + 8])
    return bytes(out)


def expand_key_7_to_8(key7: bytes) -> bytes:
    """
    把 7 字节密钥扩展为带奇偶校验位的 8 字节 DES 密钥。

    MS-CHAP 使用方式：
        21 字节密码哈希拆成 3 段，每段 7 字节，
        分别扩展为 8 字节 DES 密钥后依次加密同一个 8 字节挑战值。

    算法：
        每 7 个比特后插入 1 个奇校验位，共 56 位 -> 64 位。
    """
    if len(key7) != 7:
        raise ValueError("输入必须是 7 字节，实际=%d" % len(key7))
    bits = []
    for byte in key7:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    # bits 当前为 56 位（7 字节 × 8 位），取前 7 位一组插入校验位
    bits = bits[:56]
    out = bytearray()
    for group_start in range(0, 56, 7):
        group = bits[group_start:group_start + 7]
        parity = 1
        for bit in group:
            parity ^= bit
        out.append(int("".join(str(b) for b in group) + str(parity), 2))
    return bytes(out)
