# -*- coding: utf-8 -*-
"""
默认配置定义模块。

职责：
    定义全部可配置参数的默认值与取值范围。

三层配置（项目书第 7 节）：
    默认配置 -> config.yaml -> 生效配置

约束：
    1. Web 只能修改默认配置中已经定义的参数；
    2. Web 不得增加配置文件中不存在的配置项目；
    3. 修改后写入 data/config.yaml 并提示重启。
"""

# 默认配置字典，同时作为 Web 配置页的参数白名单
DEFAULT_CONFIG = {
    "web": {
        # 监听地址，默认仅本机
        "hosts": ["127.0.0.1", "::1"],
        # 端口为 null 时在 50000~60000 内随机选择并写回
        "port": None,
        # HTTPS 默认开启
        "https": True,
    },
    "log": {
        # 日志等级：DEBUG / INFO / WARNING / ERROR / CRITICAL
        "level": "INFO",
    },
    "test": {
        # 测试速率：每秒发起的完整认证会话数
        "rate": 10,
        # 最大并发：同时存在的最大在途测试任务数量
        "max_concurrency": 10000,
        # 单个 RADIUS 请求超时（秒）
        "timeout": 5.0,
        # 超时重试次数
        "retry_count": 3,
        # 计费 Interim-Update 间隔（秒），0 表示不发送
        "interim_interval": 60,
        # 连续多少次 Interim-Update 失败判定为掉线
        "interim_max_fail": 3,
    },
    "storage": {
        # 是否保存 RADIUS 原始报文，关闭时只保存认证状态
        "save_packets": False,
    },
    "radius": {
        # MS-CHAP v2 ChallengeHash 中 Peer-Challenge 使用的字节数。
        # RFC 2759 伪代码写 16，但 pppd 等参考客户端实现取 8，
        # 与线上服务器不一致时可切换为 16 做兼容性验证。
        "mschap_peer_challenge_bytes": 8,
    },
    # RADIUS Server 列表，字段见项目书第 12 节
    "radius_servers": [],
}

# 单个 RADIUS Server 的字段定义与默认值
SERVER_FIELDS = {
    "name": "",
    "server_address": "",
    "authentication_port": 1812,
    "accounting_port": 1813,
    "nas_ip_address": "",
    "source_address": "",
    "shared_secret": "",
    "timeout": 5.0,
    "retry_count": 3,
    "protocol": "pap",
    "enabled": True,
}

# 支持的认证协议
SUPPORTED_PROTOCOLS = ("pap", "chap", "mschap", "mschapv2", "eap-md5")

# config.yaml 初始模板
CONFIG_YAML_TEMPLATE = """# Radius-Test 配置文件
#
# 本文件由程序自动生成，用户可直接编辑。
# 仅支持修改默认配置中已定义的参数，未知参数将被忽略。
# 修改完成后需要重启程序才能生效。

web:
  hosts:
    - 127.0.0.1
    - ::1
  port: null
  https: true

log:
  level: INFO

test:
  rate: 10
  max_concurrency: 10000
  timeout: 5.0
  retry_count: 3
  interim_interval: 60
  interim_max_fail: 3

storage:
  save_packets: false

radius:
  mschap_peer_challenge_bytes: 8

radius_servers: []
"""


def default_config() -> dict:
    """返回默认配置的深拷贝，避免调用方修改污染默认值。"""
    import copy

    return copy.deepcopy(DEFAULT_CONFIG)


def default_server() -> dict:
    """返回单个 RADIUS Server 的默认值。"""
    import copy

    return copy.deepcopy(SERVER_FIELDS)
