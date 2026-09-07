# -*- coding: utf-8 -*-
"""
路径解析模块。

职责：
    统一提供程序运行所需的全部路径，屏蔽「源码运行」与「PyInstaller 打包后运行」的差异。

设计要点：
    1. 冻结环境（PyInstaller onefile）下，数据目录必须放在可执行文件所在目录，
       而不是临时解包目录（sys._MEIPASS），否则重启后数据丢失。
    2. 源码环境下，数据目录放在 main.py 所在目录。
    3. 本模块只做路径计算，不创建目录；目录创建由 bootstrap 模块负责。
"""

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """判断当前是否运行在 PyInstaller 冻结环境中。"""
    return bool(getattr(sys, "frozen", False))


def base_dir() -> Path:
    """
    返回程序根目录。

    冻结环境：可执行文件所在目录。
    源码环境：本文件向上三级（src/common/paths.py -> 项目根）。
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def data_dir() -> Path:
    """运行数据目录 data/。"""
    return base_dir() / "data"


def log_dir() -> Path:
    """日志目录 log/。"""
    return base_dir() / "log"


def dictionaries_dir() -> Path:
    """自定义 Dictionary 目录 data/dictionaries/。"""
    return data_dir() / "dictionaries"


def config_path() -> Path:
    """主配置文件 data/config.yaml。"""
    return data_dir() / "config.yaml"


def radius_yaml_path() -> Path:
    """模板登记文件 data/radius.yaml。"""
    return data_dir() / "radius.yaml"


def users_csv_path() -> Path:
    """用户主数据 data/users.csv。"""
    return data_dir() / "users.csv"


def db_path() -> Path:
    """测试结果数据库 data/results.db。"""
    return data_dir() / "results.db"


def cert_path() -> Path:
    """HTTPS 证书 data/server.crt。"""
    return data_dir() / "server.crt"


def key_path() -> Path:
    """HTTPS 私钥 data/server.key。"""
    return data_dir() / "server.key"


def src_dir() -> Path:
    """源码目录 src/。"""
    return Path(__file__).resolve().parent.parent


def dictionary_data_dir() -> Path:
    """
    内置 Dictionary 配置文件目录 src/dictionary/data/。

    该目录位于源码内部，随 PyInstaller 一起打包，用户不可直接修改。
    """
    return src_dir() / "dictionary" / "data"


def web_dir() -> Path:
    """Web 资源目录 web/。"""
    return base_dir() / "web"


def resource_dir() -> Path:
    """
    资源根目录。

    冻结环境取 PyInstaller 临时解包目录（sys._MEIPASS），源码环境取项目根目录。
    用于定位打包进去的 web/ 与 src/dictionary/data/。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return base_dir()


def builtin_web_dir() -> Path:
    """打包内置的 Web 静态资源目录。"""
    return resource_dir() / "web"


def builtin_dictionary_dir() -> Path:
    """打包内置的 Dictionary 目录。"""
    return resource_dir() / "src" / "dictionary" / "data"


def ensure_runtime_dirs() -> None:
    """创建运行时目录（存在则跳过，绝不清空已有内容）。"""
    for d in (data_dir(), log_dir(), dictionaries_dir()):
        os.makedirs(d, exist_ok=True)
