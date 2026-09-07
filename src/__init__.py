# -*- coding: utf-8 -*-
"""
Radius-Test 源码包。

模块划分（项目书第 4 节）：
    common          公共工具（时间、文件、YAML、CSV、UUID、网络、校验、密码学基础）
    config          默认配置与三层配置加载
    radius          RADIUS 协议编解码、认证器、UDP Socket 池、客户端
    authentication  认证协议（PAP / CHAP / MS-CHAP v1 / MS-CHAP v2 / EAP-MD5）
    authorization   授权属性解析
    accounting      计费与在线会话管理
    testing         测试状态、单用户任务、测试会话
    performance     速率限制与并发控制
    dictionary      内置与自定义 Dictionary 管理
    parser          报文解析与模板匹配
    database        SQLite 表结构、异步写入与查询
    certificate     HTTPS 自签证书
    logging         统一日志
    web             FastAPI 应用与接口
"""
