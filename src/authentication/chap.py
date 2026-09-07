# -*- coding: utf-8 -*-
"""
CHAP 认证模块。

职责：
    构造 CHAP 认证所需的 CHAP-Password 与 CHAP-Challenge 属性。

算法（RFC 1994）：
    CHAP-Password = CHAP-ID || MD5(CHAP-ID + 明文密码 + Challenge)

Challenge 取值规则（RFC 2865 2.2）：
    若请求中携带 CHAP-Challenge 属性（编号 60），则 Challenge 取该属性值；
    否则 Challenge 取 RADIUS Request Authenticator。
"""

import hashlib
import os


def new_chap_id() -> int:
    """生成 1 字节 CHAP 标识符。"""
    return os.urandom(1)[0]


def new_chap_challenge(length: int = 16) -> bytes:
    """生成 CHAP 挑战值，默认 16 字节。"""
    return os.urandom(length)


def build_chap_password(chap_id: int, password: str, challenge: bytes) -> bytes:
    """
    生成 CHAP-Password 属性值。

    参数：
        chap_id: 1 字节 CHAP 标识符
        password: 明文密码
        challenge: 挑战值字节串

    返回：
        CHAP-Password 属性值（1 字节 ID + 16 字节摘要）。
    """
    md5 = hashlib.md5()
    md5.update(bytes([chap_id & 0xFF]))
    md5.update(password.encode("utf-8"))
    md5.update(challenge)
    return bytes([chap_id & 0xFF]) + md5.digest()


def resolve_challenge(chap_challenge: bytes = None, request_authenticator: bytes = None) -> bytes:
    """
    确定实际使用的 Challenge。

    参数：
        chap_challenge: CHAP-Challenge 属性值，可为 None
        request_authenticator: 请求认证器，可为 None

    返回：
        实际 Challenge 字节串；两者都未提供时返回 16 字节零。
    """
    if chap_challenge:
        return chap_challenge
    if request_authenticator:
        return request_authenticator
    return bytes(16)
