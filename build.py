# -*- coding: utf-8 -*-
"""
Radius-Test 跨平台打包脚本（Windows / Linux 通用）。

用法：
    python build.py

产物：
    Windows：dist/Radius-Test.exe
    Linux  ：dist/Radius-Test

说明：
    1. 单文件 + 控制台模式：控制台需要展示软件名称、版本、访问地址与安全提示；
    2. web/ 与 src/dictionary/data/ 作为数据文件打进包内，运行时由
       paths.resource_dir() 从 sys._MEIPASS 定位，程序完全离线可用；
    3. data/ 与 log/ 不打包，运行期在可执行文件所在目录自动创建；
    4. uvicorn 的 loops/protocols/lifespan 为动态导入，必须显式声明 hidden-import；
    5. --add-data 的分隔符 Windows 为分号、Linux 为冒号，由脚本自动判断。

退出码：
    0 打包成功；1 打包失败或产物缺失。
"""
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

# 本脚本位于仓库根目录（即“源代码”目录）
SOURCE = Path(__file__).resolve().parent
DIST = SOURCE / "dist"
BUILD = SOURCE / ".build"

HIDDEN_IMPORTS = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "websockets.legacy",
    "cryptography.hazmat.primitives.asymmetric",
    "cryptography.hazmat.primitives.ciphers",
]

EXCLUDES = [
    "tkinter",
    "matplotlib",
    "numpy",
    "PIL",
    "pytest",
]


def is_windows() -> bool:
    """判断当前是否为 Windows 平台。"""
    return sys.platform.startswith("win")


def data_separator() -> str:
    """返回 PyInstaller --add-data 的分隔符。"""
    return ";" if is_windows() else ":"


def output_name() -> str:
    """返回产物文件名（Windows 由 PyInstaller 自动补 .exe，此处统一用基名）。"""
    return "Radius-Test"


def main() -> int:
    """执行打包。"""
    if not (SOURCE / "main.py").exists():
        print("未找到 main.py，无法打包（请在仓库根目录执行）")
        return 1
    if BUILD.exists():
        shutil.rmtree(BUILD, ignore_errors=True)

    separator = data_separator()
    args = [
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        "--name", output_name(),
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
        # 使用等号形式，避免 Windows 盘符冒号被误判为分隔符
        "--add-data=%s%sweb" % (SOURCE / "web", separator),
        "--add-data=%s%ssrc/dictionary/data" % (
            SOURCE / "src" / "dictionary" / "data", separator),
        "--paths", str(SOURCE),
    ]
    for module in HIDDEN_IMPORTS:
        args.extend(["--hidden-import", module])
    for module in EXCLUDES:
        args.extend(["--exclude-module", module])
    args.append(str(SOURCE / "main.py"))

    print("打包参数：")
    for item in args:
        print("  %s" % item)
    PyInstaller.__main__.run(args)

    target = DIST / (output_name() + (".exe" if is_windows() else ""))
    if target.exists():
        print("")
        print("打包完成：%s（%.1f MB）" % (target, target.stat().st_size / 1024 / 1024))
        return 0
    print("")
    print("打包失败：未找到产物 %s" % target)
    return 1


if __name__ == "__main__":
    sys.exit(main())
