[English](README.md) | 中文文档

# Benchmark Platform

CTF 靶场竞赛平台，用于安全能力评估。基于 Docker Compose 动态管理靶机实例，提供 Web UI 和 API 两种交互方式。

## 功能

- 靶机生命周期管理（启动/停止/健康检测）
- **动态 Flag 注入** — 每个实例启动时生成唯一 `flag{uuid}`，不烘焙进镜像
- **靶场商店** — 从 GitHub Releases 浏览、下载、导入靶场，支持国内镜像加速
- **热加载** — 下载新靶场后无需重启服务即可自动发现
- 多 Flag 支持（单题多个攻击路径）
- 难度分级与 Level Gate（逐级解锁）
- 实时状态展示（running / unhealthy / stopped）
- 提交记录与积分统计（跨重启持久化）
- Hint 提示系统（带扣分机制）
- 镜像预构建/缓存页面（避免冷启动延迟，**支持选择性构建**）
- 团队管理与多队伍评分
- 运行时目录隔离（可通过 Web UI 配置）
- **MCP Server** — Streamable HTTP 端点，支持 AI Agent 直接接入（Claude Code、LangChain、openai-agents 等）
- **Web UI 认证** — 基于 Cookie 的登录机制，支持管理员/观察者角色；Admin Token 自动生成或用户自定义
- Apple Silicon (ARM64) 兼容

## 界面截图

| 仪表盘 | 题目列表 |
|--------|---------|
| ![仪表盘](.github/screenshots/dashboard.png) | ![题目列表](.github/screenshots/challenges.png) |

| 靶场管理 | 镜像预热 |
|---------|---------|
| ![靶场管理](.github/screenshots/store.png) | ![镜像预热](.github/screenshots/prebuild.png) |

## 快速开始

### 环境要求

- Python >= 3.10
- Docker & Docker Compose
- sshpass（仅部署脚本需要）

### 安装

```bash
# 创建虚拟环境
python3 -m venv venv

# 激活
source venv/bin/activate

# 安装项目（虚拟环境里没有系统包的干扰）
pip install -e . -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
```

### 准备靶场题目

启动平台后，在 Web UI 侧边栏点击 **「靶场管理」** 即可浏览并下载靶场题目。

也可以手动拉取：

```bash
git clone https://github.com/wgpsec/benchmark-challenges /tmp/benchmarks
mkdir -p challenges
cp -r /tmp/benchmarks/xbow challenges/xbow
cp -r /tmp/benchmarks/custom challenges/custom
rm -rf /tmp/benchmarks
```

### 启动服务

```bash
python3 -m benchmark_platform.server \
  --benchmark-folder ./challenges \
  --port 8088 \
  --public-accessible-host localhost
```

常用参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--benchmark-folder` | 靶机题目目录（可多次指定） | 必填 |
| `--benchmark-id` / `-i` | 只加载指定 ID 的题目 | 全部加载 |
| `--challenges-dir` | 靶场管理下载根目录 | `./challenges` |
| `--admin-token` | Web UI 管理员 Token（不指定则随机生成） | 随机 |
| `--host` | 监听地址 | `0.0.0.0` |
| `--port` | 服务端口 | 8088 |
| `--public-accessible-host` | 靶机入口地址 | localhost |
| `--no-level-gate` | 禁用分级解锁 | false |

`--admin-token` 也可通过环境变量 `ADMIN_TOKEN` 设置。启动时控制台会打印当前生效的 Admin Token。

### 访问

启动后浏览器打开 `http://localhost:8088`，会跳转到登录页。输入控制台打印的 Admin Token 即可获得完整管理权限。各参赛队伍使用自己的 Agent-Token 登录后只能查看只读积分榜。

## 项目结构

```
benchmark_platform/
├── server.py              # FastAPI 入口，API 路由
├── base.py                # 核心数据模型（Challenge, FlagState 等）
├── mcp_server.py          # MCP Server（5 个工具，Streamable HTTP）
├── auth.py                # Agent-Token 认证
├── db.py                  # SQLite 持久化（团队、进度、设置）
├── models/
│   └── benchmark.py       # Benchmark JSON schema
├── utils/
│   ├── challenge.py       # ChallengeManager（实例生命周期、动态 Flag 注入）
│   └── logger.py          # 结构化日志
├── web/
│   ├── routes.py          # Web UI 页面 & HTMX partial 路由
│   ├── auth_middleware.py # Cookie 会话认证（管理员/观察者角色）
│   ├── context.py         # 模板上下文构建
│   ├── prebuild_manager.py # 镜像预构建管理器
│   ├── submission_store.py # 提交记录持久化
│   ├── store.py           # 靶场商店（GitHub Releases 下载）
│   └── templates/         # Jinja2 模板
└── static/
    └── css/app.css

scripts/                   # 部署辅助脚本
challenges/                # 靶机题目源码（git ignored）
runtime/                   # 运行时实例副本（git ignored）
tests/                     # 测试
```

## API

### Web UI

| 路由 | 说明 |
|------|------|
| `GET /web/login` | 登录页 |
| `GET /web/scoreboard` | 观察者积分榜（只读） |
| `GET /web/dashboard` | 仪表盘 |
| `GET /web/challenges` | 题目列表 |
| `GET /web/history` | 提交记录 |
| `GET /web/status` | 实例状态 |
| `GET /web/store` | 靶场管理（下载/导入） |
| `GET /web/prebuild` | 镜像预热 |
| `GET /web/teams` | 团队管理 |
| `GET /web/settings` | 平台设置 |

### REST API

所有接口均需 `Agent-Token` 请求头。标记 🔒 的接口需要管理员（默认团队）Token。

| 路由 | 说明 |
|------|------|
| `GET /api/challenges` | 获取所有题目 |
| `POST /api/start_challenge` | 启动靶机 `{code}` |
| `POST /api/stop_challenge` | 停止靶机 `{code}` |
| `POST /api/submit` | 提交 Flag `{code, flag}` |
| `POST /api/hint` | 获取提示 `{code}` |
| `GET /api/challenges/{code}/progress` | 查询 Flag 进度 |
| `POST /api/stop_all` | 🔒 停止所有实例 |
| `POST /api/challenges/reload` | 🔒 热加载新下载的靶场 |
| `POST /api/start_level` | 🔒 启动某一等级所有靶机 |
| `POST /api/stop_level` | 🔒 停止某一等级所有靶机 |
| `GET /api/instance_statuses` | 🔒 批量查询实例状态 |

### 靶场商店 API（🔒 仅管理员）

| 路由 | 说明 |
|------|------|
| `GET /api/store/manifest` | 获取远程靶场清单 |
| `POST /api/store/download` | 按 ID 下载靶场 |
| `POST /api/store/download-all` | 按分类下载全部靶场 |
| `POST /api/store/delete` | 删除已下载的靶场 |
| `POST /api/store/import` | 导入本地 zip 文件 |

### 镜像预热 API（🔒 仅管理员）

| 路由 | 说明 |
|------|------|
| `POST /api/prebuild/start` | 开始镜像预构建（支持选择性构建 `{codes: [...]}`) |
| `POST /api/prebuild/stop` | 停止预构建 |
| `GET /api/prebuild/status` | 查询预构建进度 |
| `POST /api/prebuild/remove` | 移除单个预构建镜像 |
| `POST /api/prebuild/remove_batch` | 批量移除选中镜像 `{codes: [...]}` |
| `POST /api/prebuild/remove_all` | 移除所有预构建镜像 |

### MCP Server

平台在 `/mcp/` 路径暴露 MCP（Model Context Protocol）端点，使用 Streamable HTTP 传输协议，AI Agent 可通过标准 MCP 协议直接接入。

**工具列表：**

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `list_challenges` | 获取赛题列表及队伍进度 | — |
| `start_challenge` | 启动赛题实例 | `code` |
| `stop_challenge` | 停止运行中的实例 | `code` |
| `submit_flag` | 提交 Flag 答案 | `code`, `flag` |
| `view_hint` | 查看赛题提示（扣除总分 10%） | `code` |

**认证方式：** `Authorization: Bearer <agent_token>` 请求头。

**Claude Code 接入：**

```bash
claude mcp add benchmark-platform \
  --transport http \
  --header "Authorization: Bearer <YOUR_TOKEN>" \
  http://<SERVER_HOST>:8088/mcp/
```

**JSON 配置（Cursor、Cline、Windsurf 等）：**

```json
{
  "mcpServers": {
    "benchmark-platform": {
      "url": "http://<SERVER_HOST>:8088/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_TOKEN>"
      }
    }
  }
}
```

## Agent 自动化接入

平台支持两种 AI Agent 接入方式：

1. **MCP（推荐）** — 通过 `/mcp/` 端点 Streamable HTTP 协议接入，AI Agent 直接调用工具函数，无需手写 HTTP 请求。详见上方 [MCP Server](#mcp-server) 章节。

2. **REST API** — 标准 HTTP 接口 `/api/*`，通过 `Agent-Token: <token>` 请求头认证。详见上方 [REST API](#rest-api) 章节。

完整的 API/MCP 协议文档和接入示例（LangChain、openai-agents、Python 原生），请参考 [Tsec-Hackathon 文档](https://github.com/Yeti-791/Tsec-Hackathon/tree/main/%E7%AC%AC%E4%BA%8C%E5%B1%8A%E6%99%BA%E8%83%BD%E6%B8%97%E9%80%8F%E9%BB%91%E5%AE%A2%E6%9D%BE)。

## 题目格式

每个题目是一个目录，包含：

```
XBEN-001-24/
├── docker-compose.yml    # 必须（服务通过环境变量读取 FLAG）
├── benchmark.json        # 题目元数据（name, description, level, points）
├── benchmark.yaml        # 可选，多 flag 定义
├── .env                  # FLAG 占位符（启动时被动态 flag 替换）
└── app/ mysql/ ...       # 应用代码
```

平台在每次启动实例时注入唯一的 `flag{uuid}` — 靶场源码应从 `FLAG` 环境变量读取 flag，而非硬编码。

## 技术栈

- **后端**: FastAPI + Uvicorn
- **前端**: Jinja2 + HTMX + Alpine.js + Tailwind CSS (CDN)
- **容器**: Docker Compose
- **日志**: 结构化 JSONL

## 参考项目

- [xbow-engineering/validation-benchmarks](https://github.com/xbow-engineering/validation-benchmarks)
- [Neuro-Sploit/xbow-validation-benchmarks](https://github.com/Neuro-Sploit/xbow-validation-benchmarks)
- [Yeti-791/Tsec-Hackathon](https://github.com/Yeti-791/Tsec-Hackathon)
- [Cyberdefense/GOAD](https://github.com/Orange-Cyberdefense/GOAD)
- [dockur/windows](https://github.com/dockur/windows)

## WgpSec Agentic Ecosystem

benchmark-platform 是 **WgpSec Agentic Ecosystem** 的评估层 — 衡量 AI Agent 在真实攻防场景中的表现。

```
┌───────────────────── WgpSec Agentic Ecosystem ─────────────────────┐
│                                                                     │
│  Knowledge ➜ Service ➜ Execution ➜ Evaluation                      │
│                                                                     │
│  AboutSecurity ──▶ context1337 ──▶ tchkiller ──▶ benchmark-platform │
│  (知识库)          (MCP 服务)      (渗透Agent)     (本仓库)         │
│                                         ▲                           │
│                                    PoJun (通用求解引擎)              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

| 项目 | 定位 |
|------|------|
| [AboutSecurity](https://github.com/wgpsec/AboutSecurity) | 结构化渗透知识库（Skills, Dic, Payload, Vuln） |
| [context1337](https://github.com/wgpsec/context1337) | MCP Server — 将 AboutSecurity 转化为 AI Agent 可调用的搜索 API |
| [tchkiller](https://github.com/wgpsec/tchkiller) | 自主渗透 Agent，支持多轮决策与团队协作 |
| [benchmark-platform](https://github.com/wgpsec/benchmark-platform) | CTF 靶场平台，评估 Agent 攻防能力 |
| [benchmark-challenges](https://github.com/wgpsec/benchmark-challenges) | 靶场数据仓库 — 通过 GitHub Releases 打包分发 |
| PoJun | 通用 AI 求解引擎（私有） |

## 常见问题

### "all predefined address pools have been fully subnetted"

同时启动大量靶场时，Docker 可能耗尽网络地址空间。默认每个 network 分配一个 `/16` 子网，数量有限。

**解决方法：** 在 Docker daemon 配置中添加 `default-address-pools`（Docker Desktop → Settings → Docker Engine）：

```json
{
  "default-address-pools": [
    {
      "base": "172.17.0.0/12",
      "size": 24
    }
  ]
}
```

点击 **Apply & Restart**。这样每个 network 只分配 `/24`（254 个 IP，对靶场完全够用），可支持 4000+ 个并发 network。

## 许可证

[MIT](LICENSE)
