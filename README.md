# Radius-Test

RADIUS 认证、在线会话及性能测试工具。

- **当前版本**：见 `src/version.py` 的 `SOFTWARE_VERSION`（当前 `20260907-V3`），版本号统一在此处维护，前后端共用。
- **定位**：面向网络/安全工程师，对 RADIUS 服务器进行单用户认证验证、批量在线会话压测与报文级调试。

---

## 功能特性

- **多协议认证测试**：支持 PAP / CHAP / MS-CHAPv1 / MS-CHAPv2 / EAP 等常见认证方式。
- **用户管理**：内置用户清单（CSV），支持单用户与批量认证测试。
- **在线会话与性能测试**：可设定并发速率（连接池 + 限速器），模拟在线会话并统计成功/失败与时延。
- **RADIUS 字典**：内置 RFC2865 及 Cisco / Microsoft / DSL Forum / Huawei 厂商字典（自带中文译名），自动加载。
- **报文解析**：对 RADIUS 报文进行编解码与字段解析，便于调试。
- **Web 控制台**：原生 JavaScript 单页应用（无框架、无外部 CDN），所有图标均为自建 SVG。
- **HTTPS 本地访问**：首次启动自动生成自签名证书，提供安全的本地管理界面。
- **单文件可执行**：通过 PyInstaller 打包为单文件 EXE（Windows）/ 单文件二进制（Linux），离线可用。

---

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.12、FastAPI、Uvicorn、PyYAML、cryptography、websockets |
| 前端 | 原生 HTML/CSS/JavaScript（无框架、无外部依赖） |
| 打包 | PyInstaller 6.x（`build.py` 跨平台） |
| 持续集成 | GitHub Actions（`windows-latest` + `ubuntu-latest` 矩阵） |

> 不使用 `uvicorn[standard]`（Windows 无 uvloop）、不使用 `psutil`、不使用 `asyncio.Semaphore`（并发自实现）。

---

## 目录结构

```
源代码/
├── .github/workflows/build.yml   # CI：自动构建 Win/Linux 并可选发版
├── .gitignore
├── build.py                      # 跨平台 PyInstaller 打包脚本
├── main.py                       # 程序入口
├── requirements.txt             # 运行时依赖（精确版本）
├── requirements-build.txt        # 打包依赖（参考）
├── src/                         # 后端源码
│   ├── version.py                # 软件名称与版本号（唯一来源）
│   ├── authentication/          # PAP / CHAP / MS-CHAP / EAP
│   ├── authorization/           # 授权
│   ├── accounting/              # 计费 / 在线会话
│   ├── dictionary/              # RADIUS 字典加载与注册
│   │   └── data/*.yaml          # cisco / microsoft / dslforum / huawei / rfc2865
│   ├── performance/             # 限速器 / 连接池
│   ├── radius/                  # 报文编解码 / 客户端 / 认证器
│   ├── parser/                  # 报文解析
│   ├── database/                # 结果数据库
│   ├── certificate/             # 自签名证书
│   ├── config/                  # 配置加载
│   ├── common/                  # 通用工具
│   └── web/                     # FastAPI 路由 + 运行时 + WebSocket
├── web/                         # 前端（原生 JS SPA）
│   ├── static/css/app.css
│   ├── static/js/*.js
│   ├── static/svg/*.svg         # 全部自建 SVG 图标（无外部图片）
│   └── templates/index.html
├── GITHUB_ACTIONS_排查.md       # CI 排查列表
├── CI构建说明.md                # CI 构建文档
└── README.md
```

---

## 本地运行与构建

### 运行（开发）

```bash
python -m pip install -r requirements.txt
python main.py
```

启动后按控制台提示访问本地 HTTPS 地址（如 `https://127.0.0.1:53094/`）。
首次启动会在程序所在目录自动创建 `data/`（配置/用户/结果库）与 `log/`（日志）。

### 打包为可执行文件

```bash
# 安装打包依赖
python -m pip install -r requirements-build.txt   # 或直接 pip install pyinstaller==6.22.2

# 跨平台打包（Windows → dist/Radius-Test.exe；Linux → dist/Radius-Test）
python build.py
```

产物位于 `dist/`；`data/`、`log/` 不打包，运行时自动创建。

---

## 通过 GitHub Actions 自动构建与发版

仓库内置 CI 流水线（`.github/workflows/build.yml`）：

- **push / PR 到 main**：仅自动构建，验证能否打包成功。
- **发布 Release**（三种触发其一即可）：
  1. 推送 `v*` 标签（如 `v1.0`）；
  2. 在 Actions 页面手动运行并勾选 `release`；
  3. 修改 `src/version.py` 的版本号后推送到 main。
- **版本号**：Release 的 tag 与名称一律取自 `src/version.py` 的 `SOFTWARE_VERSION`，git tag 仅作为触发信号。
- **产物**：Windows `Radius-Test-<版本>-windows-x64.exe` 与 Linux `Radius-Test-<版本>-linux-x64`。

详细配置、触发规则与排错见：

- [CI 构建说明](./CI构建说明.md)
- [GitHub Actions 排查列表](./GITHUB_ACTIONS_排查.md)

---

## 版本号规范

遵循 `变动日期-V序号`，例如 `20260907-V3`：

- **变动日期**：本次修改的日期（YYYYMMDD）。
- **V序号**：当天第几次变动（V1、V2…）。
- 每次功能或修复都升版本号，便于用户确认运行的是哪个版本。
- 修改位置唯一：`src/version.py`（`SOFTWARE_VERSION` 与 `FRONTEND_VERSION` 保持一致）。

---

## 说明

- 本仓库根目录即 `源代码` 文件夹，已包含全部可构建内容，不含运行期自动生成的 `data/`、`log/` 与 `dist/`。
- 前端无任何外部 CDN 依赖，图标均为本地 SVG，程序完全离线可用。
