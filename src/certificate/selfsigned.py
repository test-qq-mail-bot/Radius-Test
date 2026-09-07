# -*- coding: utf-8 -*-
"""
HTTPS 自签证书模块。

职责：
    生成并维护 data/server.crt 与 data/server.key。

规则（项目书 8.4）：
    1. 存在则不处理；不存在才生成；
    2. 证书或私钥缺失任意一个，视为残缺，删除后重新生成；
    3. SAN 中包含本机全部可用网卡地址（IPv4 与 IPv6）；
    4. 用户可自行替换这两个文件。
"""

import datetime
import ipaddress
from pathlib import Path
from typing import List

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from ..common import file_util, net_util, paths
from ..common.errors import CertificateError
from ..logging import logger

# 证书有效期（天）
VALIDITY_DAYS = 3650
# RSA 密钥长度
KEY_SIZE = 2048


def cert_files_ready() -> bool:
    """判断证书与私钥是否同时存在。"""
    return paths.cert_path().is_file() and paths.key_path().is_file()


def clean_broken_state() -> None:
    """
    清理残缺证书状态。

    证书与私钥必须成对存在，任意一个缺失即删除另一个，避免加载失败。
    """
    cert_exists = paths.cert_path().is_file()
    key_exists = paths.key_path().is_file()
    if cert_exists and not key_exists:
        file_util.safe_remove(paths.cert_path())
        logger.warning("certificate", "私钥缺失，已清理残缺证书", {})
    elif key_exists and not cert_exists:
        file_util.safe_remove(paths.key_path())
        logger.warning("certificate", "证书缺失，已清理残缺私钥", {})


def _build_san(addresses: List[str]) -> x509.SubjectAlternativeName:
    """根据地址列表构造 SAN 扩展。"""
    entries = []
    for address in addresses:
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(address)))
        except ValueError:
            entries.append(x509.DNSName(address))
    # 始终包含本地主机名与 localhost
    import socket

    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = "localhost"
    entries.append(x509.DNSName("localhost"))
    entries.append(x509.DNSName(hostname))
    return x509.SubjectAlternativeName(entries)


def generate_self_signed() -> None:
    """生成自签证书与私钥并写入 data/。"""
    addresses = net_util.get_all_local_addresses()
    key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Radius-Test"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Radius-Test Local Service"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=VALIDITY_DAYS))
        .add_extension(_build_san(addresses), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    file_util.write_bytes_atomic(paths.cert_path(), cert_pem)
    file_util.write_bytes_atomic(paths.key_path(), key_pem)
    logger.info(
        "certificate",
        "已生成自签 HTTPS 证书",
        {"san_count": len(addresses), "validity_days": VALIDITY_DAYS},
    )


def ensure_certificate() -> None:
    """
    确保证书可用。

    流程：
        存在且不残缺 -> 直接使用；
        残缺 -> 清理后重新生成；
        不存在 -> 生成。
    """
    paths.ensure_runtime_dirs()
    clean_broken_state()
    if cert_files_ready():
        logger.info("certificate", "使用已有 HTTPS 证书", {"path": str(paths.cert_path())})
        return
    generate_self_signed()


def load_certificate_fingerprint() -> str:
    """
    返回证书 SHA256 指纹（冒号分隔十六进制）。

    用于在页面上提示用户核对证书，避免中间人风险。
    """
    if not paths.cert_path().is_file():
        return ""
    try:
        data = file_util.read_bytes(paths.cert_path())
        cert = x509.load_pem_x509_certificate(data)
        digest = cert.fingerprint(hashes.SHA256())
        return ":".join("%02X" % b for b in digest)
    except Exception as exc:
        raise CertificateError("证书解析失败", "原因=%s" % exc)
