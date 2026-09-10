# -*- coding: utf-8 -*-
"""
RADIUS 认证器与加密模块。

职责：
    1. 生成 Request Authenticator（16 字节随机数）；
    2. 校验 Response Authenticator；
    3. User-Password 加密（RFC 2865 5.2）；
    4. Message-Authenticator 计算与校验（RFC 2869 5.14）。

说明：
    Response Authenticator = MD5(Code + ID + Length + RequestAuth + Attributes + Secret)
"""

import hashlib
import hmac
import os

from . import codes

# Request Authenticator 长度
AUTHENTICATOR_LENGTH = 16
# User-Password 加密块大小
PASSWORD_BLOCK_SIZE = 16


def new_request_authenticator() -> bytes:
    """生成 16 字节随机 Request Authenticator。"""
    return os.urandom(AUTHENTICATOR_LENGTH)


def compute_response_authenticator(
    code: int,
    identifier: int,
    length: int,
    request_authenticator: bytes,
    attributes: bytes,
    secret: bytes,
) -> bytes:
    """
    计算 Response Authenticator。

    参数：
        code: 报文类型
        identifier: 报文标识
        length: 报文总长度
        request_authenticator: 对应请求的 16 字节认证器
        attributes: 响应报文属性区字节串
        secret: 共享密钥

    返回：
        16 字节摘要。
    """
    md5 = hashlib.md5()
    md5.update(bytes([code, identifier]))
    md5.update(length.to_bytes(2, "big"))
    md5.update(request_authenticator)
    md5.update(attributes)
    md5.update(secret)
    return md5.digest()


def verify_response_authenticator(
    code: int,
    identifier: int,
    length: int,
    request_authenticator: bytes,
    attributes: bytes,
    secret: bytes,
    received_authenticator: bytes,
) -> bool:
    """
    校验响应报文的 Authenticator。

    返回：
        True 表示校验通过。
    """
    expected = compute_response_authenticator(
        code, identifier, length, request_authenticator, attributes, secret
    )
    return hmac.compare_digest(expected, received_authenticator)


def encrypt_user_password(password: str, secret: bytes, request_authenticator: bytes) -> bytes:
    """
    加密 User-Password（RFC 2865 5.2）。

    算法：
        1. 密码补齐到 16 字节整数倍，不足补 0，超过 128 字节截断；
        2. b1 = MD5(Secret + RA)，c1 = p1 XOR b1；
        3. b2 = MD5(Secret + c1)，c2 = p2 XOR b2，依此类推。

    参数：
        password: 明文密码
        secret: 共享密钥字节串
        request_authenticator: 16 字节请求认证器

    返回：
        加密后的字节串，长度为 16 的整数倍且至少 16 字节。
    """
    raw = password.encode("utf-8")
    if len(raw) > 128:
        raw = raw[:128]
    padded = bytearray(raw)
    if len(padded) == 0:
        padded = bytearray(PASSWORD_BLOCK_SIZE)
    while len(padded) % PASSWORD_BLOCK_SIZE != 0:
        padded.append(0)
    result = bytearray()
    previous = request_authenticator
    for offset in range(0, len(padded), PASSWORD_BLOCK_SIZE):
        digest = hashlib.md5(secret + previous).digest()
        block = bytes(
            padded[offset + i] ^ digest[i] for i in range(PASSWORD_BLOCK_SIZE)
        )
        result += block
        previous = block
    return bytes(result)


def decrypt_user_password(encrypted: bytes, secret: bytes, request_authenticator: bytes) -> bytes:
    """
    解密 User-Password，用于自检与报文解析展示。

    参数：
        encrypted: 加密后的字节串
        secret: 共享密钥
        request_authenticator: 16 字节请求认证器

    返回：
        解密后的原始字节串（尾部补零未去除）。
    """
    result = bytearray()
    previous = request_authenticator
    for offset in range(0, len(encrypted), PASSWORD_BLOCK_SIZE):
        block = encrypted[offset:offset + PASSWORD_BLOCK_SIZE]
        digest = hashlib.md5(secret + previous).digest()
        result += bytes(block[i] ^ digest[i] for i in range(PASSWORD_BLOCK_SIZE))
        previous = block
    return bytes(result)


def compute_message_authenticator(
    code: int,
    identifier: int,
    length: int,
    request_authenticator: bytes,
    attributes: bytes,
    secret: bytes,
) -> bytes:
    """
    计算 Message-Authenticator（RFC 2869 5.14）。

    算法（RFC 2869 5.14）：
        把 Message-Authenticator 属性值置为 16 字节零，
        以共享密钥为密钥，对完整报文
        (Code + ID + Length + RequestAuthenticator + Attributes)
        做 HMAC-MD5。

    参数：
        attributes: 属性区字节串，其中的 Message-Authenticator 必须为 16 字节零

    返回：
        16 字节 HMAC 值。
    """
    message = bytes([code, identifier])
    message += length.to_bytes(2, "big")
    message += request_authenticator
    message += attributes
    return hmac.new(secret, message, hashlib.md5).digest()


def build_message_authenticator_placeholder(attr_id: int = codes.ATTR_MESSAGE_AUTHENTICATOR) -> bytes:
    """
    构造 Message-Authenticator 占位属性。

    返回：
        属性 TLV 字节串，值为 16 字节零。
    """
    return bytes([attr_id, 2 + AUTHENTICATOR_LENGTH]) + bytes(AUTHENTICATOR_LENGTH)


def replace_message_authenticator(attributes: bytes, value: bytes,
                                  attr_id: int = codes.ATTR_MESSAGE_AUTHENTICATOR) -> bytes:
    """
    把属性区中的 Message-Authenticator 占位属性替换为真实值。

    参数：
        attributes: 原始属性区字节串
        value: 16 字节 HMAC 值
        attr_id: 属性编号

    返回：
        替换后的属性区字节串。
    """
    out = bytearray()
    offset = 0
    total = len(attributes)
    replaced = False
    while offset + 2 <= total:
        cur_id = attributes[offset]
        cur_len = attributes[offset + 1]
        if cur_len < 2 or offset + cur_len > total:
            out += attributes[offset:]
            break
        if cur_id == attr_id and cur_len == 2 + AUTHENTICATOR_LENGTH and not replaced:
            out += bytes([cur_id, cur_len]) + value
            replaced = True
        else:
            out += attributes[offset:offset + cur_len]
        offset += cur_len
    return bytes(out)
