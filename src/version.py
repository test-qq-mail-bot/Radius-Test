# -*- coding: utf-8 -*-
"""
软件名称与版本定义。

项目书第 5 节要求：
    软件名称和版本号直接写入源代码，不得建立单独的软件名称配置文件。
    前端和后端统一从该源码定义读取。

全程序使用同一个版本号（SOFTWARE_VERSION），不区分前端版本与后端版本。

以下位置必须保持一致：
    - Web 页面标题
    - 浏览器 Debug 信息
    - 后端日志
    - 软件控制台
    - 测试结果环境信息
    - 系统配置页
"""

# 软件名称
SOFTWARE_NAME = "Radius-Test"
# 软件版本号（命名规则：变动日期-V序号，如 2026-09-10 第一个版本为 20260910-V1）。
# 全程序（后端、前端、日志、页面、测试结果）统一使用这一个版本号，不分层维护。
SOFTWARE_VERSION = "20260911-V1"
# 供 Windows 可执行文件「详细信息」属性页使用的四段版本号 (major, minor, patch, build)，
# 由打包脚本 build.py 读取；与 SOFTWARE_VERSION 保持一致（build 即 V 序号）。
SOFTWARE_VERSION_TUPLE = (2026, 9, 11, 1)
# 项目定位描述
SOFTWARE_DESCRIPTION = "RADIUS 认证、在线会话及性能测试工具"
