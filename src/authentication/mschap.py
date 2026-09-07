# -*- coding: utf-8 -*-
"""
MS-CHAP v1 / v2 认证模块。

职责：
    构造 MS-CHAP v1 与 MS-CHAP v2 在 RADIUS 中所需的属性值。

依赖：
    MD4 与单 DES 由项目内部实现（src/common/md4.py、src/common/des.py），
    不依赖系统 OpenSSL Legacy Provider。

参考：
    RFC 2433  Microsoft PPP CHAP Extensions（MS-CHAP v1）
    RFC 2548  Microsoft Vendor-specific RADIUS Attributes
    RFC 2759  Microsoft PPP CHAP Extensions, Version 2
"""

import hashlib
import os
from typing import Optional

from ..common import des, md4

# Microsoft 厂商编号
VENDOR_ID_MICROSOFT = 311
# Microsoft 属性编号（RFC 2548）
MS_ATTR_CHAP_CHALLENGE = 11
MS_ATTR_CHAP_RESPONSE = 1
MS_ATTR_CHAP2_RESPONSE = 25
MS_ATTR_CHAP2_SUCCESS = 26
MS_ATTR_MPPE_SEND_KEY = 16
MS_ATTR_MPPE_RECV_KEY = 17

# RFC 2759 8.7 中的 Magic1（用于生成 Authenticator Response）
MAGIC1 = (
    b"Magic server to client signing constant"
    b"Magic server to client signing constant"
)
# RFC 2759 8.8 中的 Magic2
MAGIC2 = (
    b"Magic client to server signing constant"
    b"Magic client to server signing constant"
)

# 模块内 DESKey 缓存：同一密码哈希的轮密钥完全相同，缓存后可显著提速
_key_cache: dict = {}


def nt_password_hash(password: str) -> bytes:
    """
    计算 NtPasswordHash = MD4(UTF-16LE(密码))。

    参数：
        password: 明文密码

    返回：
        16 字节哈希。
    """
    return md4.md4(password.encode("utf-16-le"))


def hash_nt_password_hash(password_hash: bytes) -> bytes:
    """
    计算 NtPasswordHashHash = MD4(NtPasswordHash)。

    参数：
        password_hash: 16 字节 NtPasswordHash

    返回：
        16 字节哈希。
    """
    return md4.md4(password_hash)


def lm_password_hash(password: str) -> bytes:
    """
    计算 LmPasswordHash（LAN Manager 兼容哈希）。

    算法（RFC 2433 A.2）：
        1. 密码转大写，截断或补零至 14 字节；
        2. 拆成两段 7 字节，各自扩展为 8 字节 DES 密钥；
        3. 分别加密常量串 "KGS!@#$%"；
        4. 拼接得到 16 字节。

    说明：
        现代系统默认禁用 LM 哈希，本函数仅用于兼容测试。
    """
    magic = b"KGS!@#$%"
    raw = password.upper().encode("ascii", errors="ignore")[:14]
    raw = raw + bytes(14 - len(raw))
    out = b""
    for offset in (0, 7):
        key8 = des.expand_key_7_to_8(raw[offset:offset + 7])
        out += des.DESKey(key8).encrypt_block(magic)
    return out


def challenge_hash(peer_challenge: bytes, auth_challenge: bytes, username: str) -> bytes:
    """
    计算 ChallengeHash = SHA1(PeerChallenge + AuthenticatorChallenge + UserName)[0:8]。

    参数：
        peer_challenge: 对端挑战值（MS-CHAP v2 实际实现取 8 字节）
        auth_challenge: 认证方挑战值（16 字节）
        username: 用户名（不含域名前缀）

    返回：
        8 字节挑战哈希。

    注意：
        RFC 2759 伪代码把 PeerChallenge 标注为 16 字节，
        但 MS-CHAP2-Response 报文中只携带 8 字节，
        pppd 等参考客户端实现取 8 字节。
        本项目默认取 8 字节，可通过配置项 mschap_peer_challenge_bytes 切换为 16。
    """
    digest = hashlib.sha1()
    digest.update(peer_challenge)
    digest.update(auth_challenge)
    digest.update(username.encode("utf-8"))
    return digest.digest()[:8]


def challenge_response(challenge: bytes, password_hash: bytes) -> bytes:
    """
    计算 ChallengeResponse（24 字节）。

    算法（RFC 2759 8.5）：
        1. 把 16 字节密码哈希补零至 21 字节；
        2. 拆成三段 7 字节，各自扩展为 8 字节 DES 密钥；
        3. 用三段密钥分别以 ECB 模式加密 8 字节挑战值；
        4. 拼接得到 24 字节响应。

    参数：
        challenge: 8 字节挑战值
        password_hash: 16 字节密码哈希

    返回：
        24 字节响应。
    """
    if len(challenge) != 8:
        raise ValueError("挑战值必须是 8 字节，实际=%d" % len(challenge))
    z_password_hash = password_hash + bytes(21 - len(password_hash))
    out = bytearray()
    for index in range(3):
        segment = z_password_hash[index * 7:index * 7 + 7]
        cache_key = bytes(segment)
        des_key = _key_cache.get(cache_key)
        if des_key is None:
            des_key = des.DESKey(des.expand_key_7_to_8(segment))
            _key_cache[cache_key] = des_key
        out += des_key.encrypt_block(challenge)
    return bytes(out)


def nt_challenge_response(challenge: bytes, password: str) -> bytes:
    """一步计算 NT-Response。"""
    return challenge_response(challenge, nt_password_hash(password))


def lm_challenge_response(challenge: bytes, password: str) -> bytes:
    """一步计算 LM-Response。"""
    return challenge_response(challenge, lm_password_hash(password))


def build_mschap_v1(username: str, password: str, peer_challenge_bytes: int = 8) -> dict:
    """
    构造 MS-CHAP v1 所需的全部数据。

    参数：
        username: 用户名
        password: 明文密码
        peer_challenge_bytes: 生成挑战值时的字节数，8 或 16

    返回：
        字典，包含 challenge 与 response 两个字节串。

    挑战值处理规则（与 FreeRADIUS 一致）：
        挑战值为 8 字节 -> 直接作为加密挑战值；
        挑战值为 16 字节 -> 取 ChallengeHash(前 8 字节, 后 8 字节, 用户名) 作为加密挑战值。
    """
    if peer_challenge_bytes == 16:
        raw_challenge = os.urandom(16)
        effective = challenge_hash(raw_challenge[:8], raw_challenge[8:], username)
    else:
        raw_challenge = os.urandom(8)
        effective = raw_challenge
    nt_response = nt_challenge_response(effective, password)
    # RFC 2548：MS-CHAP-Response = Ident(1) + Flags(1) + LM-Response(24) + NT-Response(24)
    # Flags 置 1 表示使用 NT-Response，LM-Response 填零
    response = bytes([0x01, 0x01]) + bytes(24) + nt_response
    return {
        "challenge": raw_challenge,
        "effective_challenge": effective,
        "response": response,
        "nt_response": nt_response,
    }


def build_mschap_v2(username: str, password: str, peer_challenge_bytes: int = 8) -> dict:
    """
    构造 MS-CHAP v2 所需的全部数据。

    参数：
        username: 用户名
        password: 明文密码
        peer_challenge_bytes: Peer-Challenge 字节数，8（默认，与 pppd 一致）或 16（RFC 伪代码）

    返回：
        字典，包含 challenge、peer_challenge、response、nt_response、effective_challenge。
    """
    auth_challenge = os.urandom(16)
    peer_challenge = os.urandom(peer_challenge_bytes)
    effective = challenge_hash(peer_challenge, auth_challenge, username)
    nt_response = nt_challenge_response(effective, password)
    # RFC 2548 4.3.2：MS-CHAP2-Response 共 50 字节
    # Ident(1) + Flags(1) + PeerChallenge(8) + Reserved(8) + NT-Response(24) + Reserved(8)
    response = (
        bytes([0x01, 0x00])
        + peer_challenge
        + bytes(8)
        + nt_response
        + bytes(8)
    )
    return {
        "challenge": auth_challenge,
        "peer_challenge": peer_challenge,
        "effective_challenge": effective,
        "response": response,
        "nt_response": nt_response,
    }


def generate_authenticator_response(
    password: str, nt_response: bytes, peer_challenge: bytes,
    auth_challenge: bytes, username: str,
) -> str:
    """
    生成客户端期望的 Authenticator Response（RFC 2759 8.7）。

    返回：
        形如 "S=XXXXXXXX..." 的 42 字符字符串。

    用途：
        可选地校验服务器返回的 MS-CHAP2-Success 是否可信（双向认证）。
    """
    password_hash = nt_password_hash(password)
    password_hash_hash = hash_nt_password_hash(password_hash)
    digest = hashlib.sha1()
    digest.update(password_hash_hash)
    digest.update(nt_response)
    digest.update(MAGIC1)
    return "S=" + digest.hexdigest().upper()


def verify_mschap2_success(expected: str, received: str) -> bool:
    """
    比对服务器返回的 MS-CHAP2-Success 与本地计算值。

    参数：
        expected: 本地计算的 Authenticator Response
        received: 服务器返回的 MS-CHAP2-Success 属性值

    返回：
        True 表示一致。
    """
    if not received:
        return False
    return expected.strip().upper() == received.strip().upper()


def get_mschap2_success(packet) -> Optional[str]:
    """
    从响应报文中提取 MS-CHAP2-Success 明文。

    参数：
        packet: RadiusPacket 对象，属性需已完成解析

    返回：
        MS-CHAP2-Success 字符串；不存在时返回 None。
    """
    attribute = packet.find(MS_ATTR_CHAP2_SUCCESS, VENDOR_ID_MICROSOFT)
    if attribute is None:
        return None
    try:
        return attribute.raw.decode("ascii", errors="ignore")
    except Exception:
        return None


def clear_cache() -> None:
    """清空 DESKey 缓存。"""
    _key_cache.clear()
