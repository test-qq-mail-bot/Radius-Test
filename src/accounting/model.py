# -*- coding: utf-8 -*-
"""
在线会话数据模型。

从 acct.py 拆分而来（单文件 ≤20KB 约束）：`acct.py` 只保留 OnlineSessionManager
的调度与判定逻辑，会话实体本身独立成本模块。
`acct.py` 顶部 `from .model import OnlineSession` 属再导出，
`acct_mod.OnlineSession` 的既有导入路径保持可用。
"""

import time


class OnlineSession:
    """
    单个在线会话。

    属性：
        username: 用户名
        server_name: RADIUS Server 名称
        session_id: 计费会话 ID
        start_time: 上线时间戳（秒）
        interim_fail_count: 连续 Interim-Update 失败次数
        last_interim_time: 上次发送 Interim-Update 的时间戳
        offline: 是否已掉线
        dot1x: 该会话使用的 Dot1X 接入配置（与认证报文同一份），
            供后台 Interim-Update 复用，保证认证与计费报文属性一致
    """

    __slots__ = ("username", "server_name", "session_id", "start_time",
                 "interim_fail_count", "last_interim_time", "offline",
                 "protocol", "task_id", "interim_disabled",
                 "has_dropped", "offline_start_time", "dot1x")

    def __init__(self, username: str, server_name: str, session_id: str,
                 protocol: str = "", task_id: str = "",
                 interim_disabled: bool = False, dot1x: dict = None):
        self.username = username
        self.server_name = server_name
        self.session_id = session_id
        self.protocol = protocol
        self.task_id = task_id
        # True 表示该会话不参与 Interim-Update 掉线判定
        # （用于「认证成功即在线」口径下计费未上线的会话）
        self.interim_disabled = interim_disabled
        self.dot1x = dot1x
        self.start_time = time.time()
        self.interim_fail_count = 0
        self.last_interim_time = self.start_time
        self.offline = False
        self.has_dropped = False
        self.offline_start_time = 0.0
