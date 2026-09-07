# -*- coding: utf-8 -*-
"""
网络工具模块。

职责：
    1. 枚举本机全部可用网卡地址（IPv4 / IPv6），用于证书 SAN；
    2. 端口可用性检测与 50000~60000 随机端口选择（项目书 8.3）；
    3. 监听地址安全性判定（项目书 8.2）。
"""

import random
import socket
from typing import List

# 项目书 8.3：端口为空时在 50000~60000 范围内随机选择
PORT_RANGE_MIN = 50000
PORT_RANGE_MAX = 60000

# 项目书 8.1：默认监听地址，仅本机可访问
LOCAL_ADDRESSES = ("127.0.0.1", "::1")

# 项目书 8.2：非本地监听时需要显示的安全提示
REMOTE_LISTEN_WARNING = "请确认当前网络环境可信，否则请改回127.0.0.1和::1"


def get_all_local_addresses() -> List[str]:
    """
    返回本机全部可用网卡地址（IPv4 与 IPv6）。

    说明：
        同时返回 IPv4 与 IPv6 地址，用于生成 HTTPS 证书 SAN。
        地址已去重，链路本地地址（fe80::）不排除，因其可能被本机使用。
    """
    addresses = set()
    # 优先通过主机名解析，覆盖多网卡场景
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP):
            addresses.add(info[4][0])
    except OSError:
        pass
    # 通过 UDP 连接探测默认路由出口地址（不实际发包）
    for family, target in ((socket.AF_INET, "8.8.8.8"), (socket.AF_INET6, "2001:4860:4860::8888")):
        try:
            sock = socket.socket(family, socket.SOCK_DGRAM)
            try:
                sock.connect((target, 80))
                addresses.add(sock.getsockname()[0])
            finally:
                sock.close()
        except OSError:
            continue
    # 始终包含回环地址
    addresses.add("127.0.0.1")
    addresses.add("::1")
    return sorted(addresses)


def is_port_available(host: str, port: int) -> bool:
    """
    检测指定地址的端口是否可用。

    判定方式：尝试绑定，绑定成功即视为可用。
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def choose_random_port(host: str = "127.0.0.1") -> int:
    """
    在 50000~60000 范围内随机选择可用端口。

    参数：
        host: 检测绑定用的地址

    返回：
        可用端口号；若该区间全部被占用则抛出 OSError。
    """
    candidates = list(range(PORT_RANGE_MIN, PORT_RANGE_MAX + 1))
    random.shuffle(candidates)
    for port in candidates:
        if is_port_available(host, port):
            return port
    raise OSError("端口区间 %d~%d 内没有可用端口" % (PORT_RANGE_MIN, PORT_RANGE_MAX))


def is_local_only(hosts) -> bool:
    """
    判断监听地址集合是否仅包含本机回环地址。

    参数：
        hosts: 监听地址列表

    返回：
        True 表示仅本机监听，False 表示存在对外监听。
    """
    for host in hosts:
        h = (host or "").strip()
        if h and h not in LOCAL_ADDRESSES:
            return False
    return True


def is_valid_ip(value: str) -> bool:
    """判断字符串是否为合法 IPv4 或 IPv6 地址。"""
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.inet_pton(family, value)
            return True
        except OSError:
            continue
    return False


def resolve_host(value: str) -> str:
    """
    解析主机名；解析失败时原样返回。

    用于 RADIUS Server 地址可能是主机名的情况。
    """
    if is_valid_ip(value):
        return value
    try:
        return socket.getaddrinfo(value, None)[0][4][0]
    except OSError:
        return value
