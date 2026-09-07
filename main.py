# -*- coding: utf-8 -*-
"""
Radius-Test 程序入口。

启动流程（项目书第 29 节）：
    检查目录 -> 检查文件 -> 不存在则自动生成
    -> 读取默认配置 -> 读取 config.yaml
    -> 加载 Radius Dictionary -> 扫描自定义模板
    -> 更新 radius.yaml 模板登记
    -> 检查 HTTPS 证书 -> 启动 Web 服务

监听策略：
    默认同时监听 127.0.0.1 与 ::1。
    uvicorn 单实例只能绑定一个地址，因此本项目启动两个实例共享同一应用，
    仅第一个实例负责执行应用生命周期事件。
"""

import asyncio
import signal
import socket
import sys

import uvicorn

from src import version
from src.certificate import selfsigned as cert_mod
from src.common import file_util, net_util, paths
from src.common import csv_util
from src.config import loader
from src.database import dao
from src.dictionary import loader as dict_loader
from src.dictionary import registry
from src.logging import logger
from src.web import runtime
from src.web.app import create_app


def ensure_runtime_files() -> None:
    """确保全部运行时文件存在（存在则不处理）。"""
    file_util.create_if_missing(paths.users_csv_path(), lambda: csv_util.USER_CSV_TEMPLATE)
    registry.ensure_registry_file()
    logger.info("bootstrap", "运行时文件检查完成", {
        "config": str(paths.config_path()),
        "users": str(paths.users_csv_path()),
        "database": str(paths.db_path()),
    })


def load_dictionaries() -> int:
    """
    加载 Dictionary 模板并同步 radius.yaml 登记。

    返回：
        已加载模板数量。
    """
    store = dict_loader.get_store()
    added = registry.sync_registry(store.summary())
    logger.info("bootstrap", "Dictionary 模板加载完成", {
        "templates": len(store.templates),
        "registry_added": added,
    })
    for template in store.templates:
        logger.debug("bootstrap", "已加载 Dictionary 模板", {
            "template": template.name,
            "source": template.source,
            "attributes": template.attribute_count,
        })
    return len(store.templates)


def format_url(scheme: str, host: str, port: int) -> str:
    """
    拼接访问地址。

    说明：
        IPv6 地址在 URL 中必须用方括号包裹，否则浏览器无法解析，
        例如 https://[::1]:50000/。
    """
    if ":" in host:
        return "%s://[%s]:%d/" % (scheme, host, port)
    return "%s://%s:%d/" % (scheme, host, port)


def print_banner(config: dict, urls) -> None:
    """输出控制台启动信息。"""
    web = config.get("web", {})
    print("")
    print("%s %s" % (version.SOFTWARE_NAME, version.SOFTWARE_VERSION))
    print(version.SOFTWARE_DESCRIPTION)
    print("-" * 60)
    for url in urls:
        print("访问地址：%s" % url)
    if not net_util.is_local_only(web.get("hosts") or []):
        print("警告：%s" % net_util.REMOTE_LISTEN_WARNING)
    print("数据目录：%s" % paths.data_dir())
    print("日志目录：%s" % paths.log_dir())
    print("-" * 60)
    print("")
    # 立即刷新，保证输出被重定向到文件时也能实时看到访问地址
    sys.stdout.flush()


def build_servers(app, hosts, port, https: bool) -> list:
    """
    构造 uvicorn Server 实例列表。

    参数：
        app: FastAPI 应用
        hosts: 监听地址列表
        port: 监听端口
        https: 是否启用 HTTPS

    返回：
        (uvicorn.Server, 是否实际可用) 元组列表。

    说明：
        只有第一个实例执行应用生命周期事件，
        其余实例设置 lifespan="off"，避免重复触发 startup / shutdown。
    """
    servers = []
    ssl_args = {}
    if https:
        ssl_args = {
            "ssl_certfile": str(paths.cert_path()),
            "ssl_keyfile": str(paths.key_path()),
        }
    first = True
    for host in hosts:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        if family == socket.AF_INET6 and not socket.has_ipv6:
            logger.warning("bootstrap", "系统不支持 IPv6，跳过该监听地址", {"host": host})
            continue
        if not net_util.is_port_available(host, port) and not first:
            # 同端口多地址绑定，第二个实例不再重复检测
            pass
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            lifespan="on" if first else "off",
            log_config=None,
            access_log=True,
            **ssl_args
        )
        server = uvicorn.Server(config)
        servers.append((server, host))
        first = False
    return servers


async def run_async() -> None:
    """异步主流程。"""
    paths.ensure_runtime_dirs()
    logger.info("bootstrap", "%s 启动中" % version.SOFTWARE_NAME, {
        "version": version.SOFTWARE_VERSION,
        "python": sys.version.split()[0],
    })
    loader.ensure_config_file()
    config = loader.load_config()
    logger.set_level(str(config.get("log", {}).get("level") or "INFO"))
    ensure_runtime_files()
    load_dictionaries()
    cert_mod.ensure_certificate()
    dao.init()

    web = config.get("web", {})
    hosts = [str(h).strip() for h in (web.get("hosts") or []) if str(h).strip()]
    if not hosts:
        hosts = ["127.0.0.1", "::1"]
    port = int(web.get("port") or 0)
    https = bool(web.get("https"))

    runtime.listen_info["hosts"] = hosts
    runtime.listen_info["port"] = port
    runtime.listen_info["https"] = https
    runtime.listen_info["local_only"] = net_util.is_local_only(hosts)
    runtime.listen_info["warning"] = "" if net_util.is_local_only(hosts) \
        else net_util.REMOTE_LISTEN_WARNING

    app = create_app()
    servers = build_servers(app, hosts, port, https)
    if not servers:
        logger.error("bootstrap", "没有可用的监听地址", {"hosts": hosts})
        return

    scheme = "https" if https else "http"
    urls = [format_url(scheme, host, port) for _server, host in servers]
    print_banner(config, urls)

    tasks = [asyncio.create_task(server.serve()) for server, _host in servers]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
    finally:
        logger.info("bootstrap", "服务已停止", {})


def main() -> int:
    """程序入口。"""
    try:
        asyncio.run(run_async())
    except KeyboardInterrupt:
        print("")
        logger.info("bootstrap", "收到中断信号，程序退出", {})
        return 0
    except Exception as exc:
        logger.error("bootstrap", "程序启动失败", {"error": str(exc)}, exc_info=True)
        print("程序启动失败：%s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
