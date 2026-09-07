# -*- coding: utf-8 -*-
"""
EAP 报文编解码与 EAP-MD5 计算模块。

职责：
    1. EAP 报文编解码（RFC 3748）；
    2. EAP-Identity、EAP-Notification、EAP-MD5 的响应计算；
    3. EAP-Message 分片与重组（RFC 3579）。

EAP 报文结构（RFC 3748 第 4 节）：
    Code(1) + Identifier(1) + Length(2) + Data(...)

说明：
    Identity 与 Notification 报文的 Data 首字节即为 Type，
    但 Identity 的 Type 隐含为 1，实际实现中直接携带身份字符串。
"""

import hashlib
import struct
from typing import Tuple

# EAP 报文类型
EAP_CODE_REQUEST = 1
EAP_CODE_RESPONSE = 2
EAP_CODE_SUCCESS = 3
EAP_CODE_FAILURE = 4

EAP_CODE_NAMES = {
    EAP_CODE_REQUEST: "Request",
    EAP_CODE_RESPONSE: "Response",
    EAP_CODE_SUCCESS: "Success",
    EAP_CODE_FAILURE: "Failure",
}

# EAP 方法类型
EAP_TYPE_IDENTITY = 1
EAP_TYPE_NOTIFICATION = 2
EAP_TYPE_NAK = 3
EAP_TYPE_MD5_CHALLENGE = 4
EAP_TYPE_MSCHAPV2 = 26

EAP_TYPE_NAMES = {
    EAP_TYPE_IDENTITY: "Identity",
    EAP_TYPE_NOTIFICATION: "Notification",
    EAP_TYPE_NAK: "Nak",
    EAP_TYPE_MD5_CHALLENGE: "MD5-Challenge",
    EAP_TYPE_MSCHAPV2: "MS-CHAP-V2",
}

# EAP-MD5 挑战值长度
MD5_CHALLENGE_LENGTH = 16


def encode_eap(code: int, identifier: int, data: bytes) -> bytes:
    """
    编码 EAP 报文。

    参数：
        code: EAP Code
        identifier: EAP Identifier
        data: EAP Data 区（含 Type 字段，Identity 除外）

    返回：
        完整 EAP 报文字节串。
    """
    length = 4 + len(data)
    return struct.pack(">BBH", code, identifier & 0xFF, length) + data


def decode_eap(data: bytes) -> dict:
    """
    解码 EAP 报文。

    返回：
        字典，包含 code、code_name、identifier、length、type、type_name、value。
    """
    if len(data) < 4:
        return {
            "code": 0,
            "code_name": "Invalid",
            "identifier": 0,
            "length": len(data),
            "type": None,
            "type_name": "",
            "value": b"",
            "valid": False,
        }
    code = data[0]
    identifier = data[1]
    length = struct.unpack(">H", data[2:4])[0]
    payload = data[4:length] if length <= len(data) else data[4:]
    eap_type = None
    value = b""
    if payload:
        eap_type = payload[0]
        value = payload[1:]
    return {
        "code": code,
        "code_name": EAP_CODE_NAMES.get(code, "Unknown(%d)" % code),
        "identifier": identifier,
        "length": length,
        "type": eap_type,
        "type_name": EAP_TYPE_NAMES.get(eap_type, "") if eap_type is not None else "",
        "value": value,
        "valid": length >= 4 and length <= len(data),
    }


def build_identity_response(identifier: int, username: str) -> bytes:
    """
    构造 EAP-Response/Identity。

    参数：
        identifier: 与请求相同的 EAP Identifier
        username: 用户名

    返回：
        EAP 报文字节串。

    说明：
        RFC 3748 第 4.1 节规定 Request 与 Response 报文必须携带 Type 字段，
        Identity 的 Type 取值为 1，其后紧跟身份字符串，
        因此 Data 区结构为 Type(1)=1 + 身份字符串。
    """
    data = bytes([EAP_TYPE_IDENTITY]) + username.encode("utf-8")
    return encode_eap(EAP_CODE_RESPONSE, identifier, data)


def parse_identity(eap_data: bytes) -> str:
    """
    从 EAP-Response/Identity 的 Data 区解析身份字符串。

    参数：
        eap_data: EAP Data 区（首字节为 Type=1）

    返回：
        身份字符串；Data 为空时返回空字符串。
    """
    if not eap_data:
        return ""
    if eap_data[0] == EAP_TYPE_IDENTITY:
        return eap_data[1:].decode("utf-8", errors="ignore")
    return eap_data.decode("utf-8", errors="ignore")


def build_notification_response(identifier: int) -> bytes:
    """构造 EAP-Response/Notification（空载荷）。"""
    return encode_eap(EAP_CODE_RESPONSE, identifier, bytes([EAP_TYPE_NOTIFICATION]))


def compute_md5_challenge_response(identifier: int, password: str, challenge: bytes) -> bytes:
    """
    计算 EAP-MD5 响应值。

    算法（RFC 3748 5.4）：
        Value = MD5(EAP-Identifier + 明文密码 + Challenge)

    参数：
        identifier: 请求的 EAP Identifier
        password: 明文密码
        challenge: 16 字节挑战值

    返回：
        16 字节响应值。
    """
    digest = hashlib.md5()
    digest.update(bytes([identifier & 0xFF]))
    digest.update(password.encode("utf-8"))
    digest.update(challenge)
    return digest.digest()


def build_md5_challenge_response(identifier: int, password: str, challenge: bytes) -> bytes:
    """
    构造 EAP-Response/MD5-Challenge。

    Data 区结构：Type(1)=4 + Value-Size(1)=16 + Value(16)
    """
    value = compute_md5_challenge_response(identifier, password, challenge)
    data = bytes([EAP_TYPE_MD5_CHALLENGE, MD5_CHALLENGE_LENGTH]) + value
    return encode_eap(EAP_CODE_RESPONSE, identifier, data)


def parse_request(data: bytes) -> Tuple[int, int, bytes]:
    """
    解析 EAP 请求，提取 (EAP Code, Identifier, Data)。

    参数：
        data: 重组后的完整 EAP 报文字节串

    返回：
        (code, identifier, data)；解析失败时 code 为 0。
    """
    parsed = decode_eap(data)
    if not parsed["valid"]:
        return 0, 0, b""
    raw = data[4:parsed["length"]] if parsed["length"] <= len(data) else b""
    return parsed["code"], parsed["identifier"], raw
