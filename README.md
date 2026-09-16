# Radius-Test

RADIUS 认证、在线会话及性能测试工具。

- **当前版本**：见 `src/version.py` 的 `SOFTWARE_VERSION`（当前 `20260915-V4`）。全程序（后端、前端、日志、页面、测试结果）统一使用这一个版本号，不区分前后端版本。
- **定位**：面向网络/安全工程师，对 RADIUS 服务器进行单用户认证验证、批量在线会话压测与报文级调试。
- **许可**：MIT License（见 [LICENSE](./LICENSE)）。

---

## 功能特性

- **多协议认证测试**：支持 PAP / CHAP / MS-CHAPv1 / MS-CHAPv2 / EAP 等常见认证方式。
- **用户管理**：内置用户清单（CSV），支持单用户与批量认证测试；
  用户列表支持**表头全选、行首复选框、以及点击行累加多选**（再点一次取消）。
- **在线会话与性能测试**：可设定并发速率（连接池 + 限速器），模拟在线会话并统计成功/失败与时延；
  计费报文按 RFC 2866 计算 Request Authenticator，计费超时独立于认证超时。
- **账号认证测试保持在线**：认证成功并计费上线后保持在线（`Accounting-Start` → 后台
  `Interim-Update` 保活 → 停止时 `Accounting-Stop`）；三处入口（Server「Radius 用户测试」、
  用户列表单个/批量）与性能测试**双向互斥**。
- **Dot1X 接入配置（三个入口字段完全一致）**：接入类型（有线/无线）、SSID、`NAS-Port(5)`、
  `NAS-Port-Id(87)`、终端 MAC(`Calling-Station-Id 31`)、`NAS-Identifier(32)`、`Service-Type(6)`、
  `Framed-IP-Address(8)`、`Connect-Info(77)` 均可自定义；
  **留空时生成默认合法值并发送**，不存在「留空不发送」。
  其中 `Service-Type` 默认固定 `Framed(2)` —— 该属性参与服务端业务决策，取值有强语义约束，
  不能随机（实测部分服务端对 `Administrative(6)` 会静默丢弃报文）。
- **RADIUS 字典**：内置 15 个模板（RFC2865 及 Cisco / Microsoft / DSL Forum / Huawei / HP / H3C /
  Juniper / Mikrotik / Aruba / Fortinet / Ericsson / 3GPP / 3GPP2 等，自带中文译名），自动加载。
- **报文解析与详情**：对 RADIUS 报文编解码与字段解析；详情页按
  **认证 / Accounting-Start / Accounting-Interim / Accounting-Stop** 四组**直出**请求与响应（不再折叠）；
  同类报文**落库时即合并**，只保留最新一条；所有报文落库前完成属性解析，不会整包显示为「未知属性」。
- **测试页面心跳保护**：以「前端是否仍停在测试页面」为存活判据（页面每 2 秒上报、超过 4 秒判定失联），
  离开测试页面立即中断；浏览器标签页切到后台不算离开。
- **报文级调试日志**：日志等级 DEBUG 时输出每一次 RADIUS 收发的目标、Identifier、耗时、全部属性与原始 HEX，
  口令类属性自动打码，并按每任务条数限流。
- **Web 控制台**：原生 JavaScript 单页应用（无框架、无外部 CDN），所有图标均为自建 SVG，
  页面元素全部具备唯一 id（含运行期动态插入元素）。
- **HTTPS 本地访问**：首次启动自动生成自签名证书，提供安全的本地管理界面。
- **单文件可执行**：通过 PyInstaller 打包为单文件 EXE（Windows）/ 单文件二进制（Linux），离线可用。

---

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.12、FastAPI、Uvicorn、PyYAML、cryptography、websockets |
| 前端 | 原生 HTML/CSS/JavaScript（无框架、无外部依赖） |
| 打包 | PyInstaller 6.x（`build.py` 跨平台） |
| 持续集成 | GitHub Actions（`windows-latest` + `ubuntu-latest` 矩阵；版本号变更自动发版） |

> 不使用 `uvicorn[standard]`（Windows 无 uvloop）、不使用 `psutil`、不使用 `asyncio.Semaphore`（并发自实现）。

---

## 目录结构

```
源代码/                            # 本仓库根目录
├── .github/workflows/build.yml   # CI：构建 Win/Linux，版本号变更时自动发版
├── .gitignore
├── LICENSE                       # MIT 许可协议
├── build.py                      # 跨平台 PyInstaller 打包脚本
├── main.py                       # 程序入口
├── requirements.txt              # 运行时依赖（精确版本）
├── requirements-build.txt        # 打包依赖（Windows / Linux 共用，按平台标记）
├── src/                          # 后端源码
│   ├── version.py                # 软件名称与版本号（唯一来源）
│   ├── authentication/           # PAP / CHAP / MS-CHAP / EAP
│   ├── authorization/            # 授权
│   ├── accounting/               # 计费 / 在线会话
│   ├── dictionary/               # RADIUS 字典加载与注册
│   │   └── data/*.yaml           # 内置 15 个字典模板
│   ├── performance/              # 限速器 / 连接池
│   ├── radius/                   # 报文编解码 / 客户端 / 报文构造 / 认证器 / 收发追踪
│   ├── parser/                   # 报文解析
│   ├── database/                 # 结果数据库
│   ├── certificate/              # 自签名证书
│   ├── config/                   # 配置加载
│   ├── common/                   # 通用工具
│   └── web/                      # FastAPI 路由 + 运行时 + WebSocket + 页面心跳保护
├── web/                          # 前端（原生 JS SPA）
│   ├── static/css/app.css
│   ├── static/js/*.js
│   ├── static/svg/*.svg          # 全部自建 SVG 图标（无外部图片）
│   └── templates/index.html
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
# 安装打包依赖（Windows / Linux 共用同一份清单；Windows 专属包已用 PEP 508 环境标记标注）
python -m pip install -r requirements-build.txt

# 跨平台打包（Windows → dist/Radius-Test.exe；Linux → dist/Radius-Test）
python build.py
```

产物位于 `dist/`；`data/`、`log/` 不打包，运行时自动创建。

---

## 通过 GitHub Actions 自动构建与发版

仓库内置 CI 流水线（`.github/workflows/build.yml`）：

- **push / PR 到 main**：自动构建，验证能否打包成功（**PR 只构建，不发布**）。
- **自动发版（版本号变更即发布）**：修改 `src/version.py` 的 `SOFTWARE_VERSION` 后推送到 main，
  CI 读取该版本号并检查是否已有对应 Release，**不存在则自动构建并发布**。
  判定是**幂等**的：与一次推送包含多少个 commit 无关，重复推送同一版本也不会重复发版。
- **其它发布方式**：推送 `v*` 标签（强制发布）；或在 Actions 页面手动运行并勾选 `release`。
- **版本号**：Release 的 tag 与名称取自 `src/version.py` 的 `SOFTWARE_VERSION`。
- **产物**（每个平台二进制附一个 SHA256 校验文件）：

  | 文件 | 说明 |
  | --- | --- |
  | `Radius-Test-<版本>-windows-x64.exe` | Windows 单文件可执行 |
  | `Radius-Test-<版本>-windows-x64.exe.sha256` | 上者的 SHA256 |
  | `Radius-Test-<版本>-linux-x64` | Linux 单文件可执行 |
  | `Radius-Test-<版本>-linux-x64.sha256` | 上者的 SHA256 |

  校验方式：`sha256sum -c <文件名>.sha256`；
  Windows 可用 `Get-FileHash .\xxx.exe -Algorithm SHA256` 后与文件内摘要比对。

---

## 版本号规范

遵循 `变动日期-V序号`，例如 `20260907-V3`：

- **变动日期**：本次修改的日期（YYYYMMDD）。
- **V序号**：当天第几次变动（V1、V2…）。
- 每次功能或修复都升版本号，便于用户确认运行的是哪个版本。
- 修改位置唯一：`src/version.py` 的 `SOFTWARE_VERSION`。全程序共用一个版本号，不区分前端版本与后端版本；任何功能或修复变动都升这一个版本号。

---

## 说明

- 本仓库根目录即 `源代码` 文件夹，已包含全部可构建内容，不含运行期自动生成的 `data/`、`log/` 与 `dist/`。
- 前端无任何外部 CDN 依赖，图标均为本地 SVG，程序完全离线可用。

---

## 许可协议

本项目采用 **MIT License**，全文见 [LICENSE](./LICENSE)。

```
Copyright (c) 2026 test-qq-mail-bot
```

在遵守 MIT 条款（保留版权声明与许可声明）的前提下，可自由使用、修改、分发与商用；
软件按「原样」提供，不附带任何明示或暗示的担保。
