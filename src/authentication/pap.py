# -*- coding: utf-8 -*-
"""
PAP 认证模块。

职责：
    构造 PAP 认证所需的 User-Password 属性值。

参考：
    RFC 2865 5.2（User-Password 加密）
"""

from ..radius import authenticator


def build_pap_password(password: str, secret: bytes, request_authenticator: bytes) -> bytes:
    """
    生成加密后的 User-Password 属性值。

    参数：
        password: 明文密码
        secret: 共享密钥字节串
        request_authenticator: 16 字节请求认证器

    返回：
        加密后的字节串，直接作为 User-Password 属性值。
    """
    return authenticator.encrypt_user_password(password, secret, request_authenticator)
