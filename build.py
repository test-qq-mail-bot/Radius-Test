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
    5. --add-data 的分隔符 Windows 为分号、Linux 为冒号，由脚本自动判断；
    6. Windows 下自动生成版本资源文件并传给 --version-file，
       使 EXE「属性 - 详细信息」显示软件名称与版本号（版本源自 src/version.py）。

退出码：
    0 打包成功；1 打包失败或产物缺失。
"""
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

# 兼容非 UTF-8 控制台（如 Windows PowerShell）：强制 stdout/stderr 为 UTF-8，
# 避免打印中文时触发 UnicodeEncodeError 使进程以非零码退出（CI 中表现为 exit code 1）。
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

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


def load_version():
    """
    从 src/version.py 读取软件名称/版本（单一版本号来源）。

    说明：
        按文件路径加载，绝不把 src/ 注入 sys.path。
        因为 src/logging 会遮蔽标准库 logging（项目包名与标准库同名），
        而 PyInstaller 的子进程会继承父进程 sys.path，
        一旦注入将导致打包中途报 AttributeError: module 'logging' has no attribute 'getLogger'。
    """
    import importlib.util

    path = SOURCE / "src" / "version.py"
    spec = importlib.util.spec_from_file_location("_radius_test_version", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_version_file(target: Path) -> Path:
    """
    生成 Windows 版本资源文件（供 PyInstaller --version-file 使用）。

    内容取自 src/version.py：FileVersion 为四段数字版本，ProductVersion 为完整版本串，
    使 EXE「属性 - 详细信息」可见软件名称与版本号。
    """
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    version = load_version()
    major, minor, patch, build = version.SOFTWARE_VERSION_TUPLE
    file_version_tuple = (major, minor, patch, build)
    file_version_str = "%d.%d.%d.%d" % file_version_tuple
    info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=file_version_tuple,
            prodvers=file_version_tuple,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo([
                StringTable("080404b0", [
                    StringStruct("CompanyName", version.SOFTWARE_NAME),
                    StringStruct("FileDescription", version.SOFTWARE_DESCRIPTION),
                    StringStruct("FileVersion", file_version_str),
                    StringStruct("InternalName", version.SOFTWARE_NAME),
                    StringStruct("OriginalFilename", "Radius-Test.exe"),
                    StringStruct("ProductName", version.SOFTWARE_NAME),
                    StringStruct("ProductVersion", version.SOFTWARE_VERSION),
                ]),
            ]),
            VarFileInfo([VarStruct("Translation", [2052, 1200])]),
        ],
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    # 必须用 str(info)（PyInstaller 的 VSVersionInfo.__str__ 文本序列化格式），
    # 不能用 repr(info)：repr 会输出 versioninfo.XXX(...) 前缀，eval 时无法解析。
    target.write_text(str(info), encoding="utf-8")
    print("版本资源文件已生成：%s（%s）" % (target, version.SOFTWARE_VERSION))
    return target


def main() -> int:
    """执行打包。"""
    if not (SOURCE / "main.py").exists():
        print("未找到 main.py，无法打包（请在仓库根目录执行）")
        return 1
    if BUILD.exists():
        shutil.rmtree(BUILD, ignore_errors=True)
    BUILD.mkdir(parents=True, exist_ok=True)

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
    if is_windows():
        # 写入 Windows 版本资源，使 EXE「详细信息」页显示版本号
        args.append("--version-file=%s" % write_version_file(BUILD / "version_info.txt"))
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
