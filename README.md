[English](#english) | [中文](#中文)

---

<a name="english"></a>

# Benchmark Platform

A CTF challenge platform for security capability evaluation. Dynamically manages challenge instances via Docker Compose, with both a Web UI and REST API interface.

## Features

- Challenge lifecycle management (start / stop / health check)
- Multi-flag support (multiple attack paths per challenge)
- Difficulty tiering with Level Gate (progressive unlock)
- Real-time status display (running / unhealthy / stopped)
- Submission history & scoring
- Hint system (with point deduction)
- Image pre-build / cache page (avoid cold-start delays)
- Apple Silicon (ARM64) compatibility

## Quick Start

### Requirements

- Python >= 3.10
- Docker & Docker Compose
- sshpass (deployment scripts only)

### Install

```bash
pip install -e .
```

### Run

```bash
python -m benchmark_platform.server \
  --benchmark-folder ./challenges \
  --port 8088 \
  --public-accessible-host localhost
```

Options:

| Flag | Description | Default |
|------|-------------|---------|
| `--benchmark-folder` | Challenge directory (can be repeated) | required |
| `--benchmark-id` / `-i` | Load only specific IDs | all |
| `--port` | Server port | 8088 |
| `--public-accessible-host` | Public hostname for challenges | localhost |
| `--no-level-gate` | Disable level-based unlock | false |

### Access

Open `http://localhost:8088` in your browser after starting the server.

## Project Structure

```
benchmark_platform/
├── server.py              # FastAPI entry, API routes
├── base.py                # Core models (Challenge, FlagState, etc.)
├── models/
│   └── benchmark.py       # Benchmark JSON schema
├── utils/
│   ├── challenge.py       # ChallengeManager (instance lifecycle)
│   └── logger.py          # Structured logging
├── web/
│   ├── routes.py          # Web UI page & HTMX partial routes
│   ├── context.py         # Template context builders
│   ├── prebuild_manager.py # Image pre-build manager
│   ├── submission_store.py # Submission persistence
│   └── templates/         # Jinja2 templates
└── static/
    └── css/app.css

scripts/                   # Deployment helper scripts
challenges/                # Challenge source code (git ignored)
tests/                     # Tests
```

## API

### Web UI

| Route | Description |
|-------|-------------|
| `GET /web/dashboard` | Dashboard |
| `GET /web/challenges` | Challenge list |
| `GET /web/history` | Submission history |
| `GET /web/status` | Instance status |
| `GET /web/prebuild` | Image pre-build |

### REST API

| Route | Description |
|-------|-------------|
| `GET /api/challenges` | List all challenges |
| `POST /api/start_challenge` | Start instance `{code}` |
| `POST /api/stop_challenge` | Stop instance `{code}` |
| `POST /api/submit` | Submit flag `{code, flag}` |
| `POST /api/hint` | Get hint `{code}` |
| `POST /api/stop_all` | Stop all instances |
| `GET /api/challenges/{code}/progress` | Query flag progress |

## Challenge Format

Each challenge is a directory containing:

```
XBEN-001-24/
├── docker-compose.yml    # Required
├── benchmark.json        # Metadata (name, description, level, points)
├── benchmark.yaml        # Optional, multi-flag definitions
├── .env                  # FLAG environment variable
└── app/ mysql/ ...       # Application code
```

## Deployment Scripts

Pre-build images on Mac and transfer to VM:

```bash
# 1. Build all challenge images
bash scripts/build_and_save_challenges.sh

# 2. Transfer to VM
VM_HOST=10.x.x.x VM_PORT=22 VM_USER=root VM_PASS=xxx \
  bash scripts/load_challenges_on_vm.sh

# 3. Pre-build on VM (if not transferred via images)
bash scripts/prebuild_on_vm.sh
```

## Tech Stack

- **Backend**: FastAPI + Uvicorn
- **Frontend**: Jinja2 + HTMX + Alpine.js + Tailwind CSS (CDN)
- **Containers**: Docker Compose
- **Logging**: Structured JSONL

## WgpSec Agentic Ecosystem

benchmark-platform is the evaluation layer of the **WgpSec Agentic Ecosystem** — measuring how well AI agents perform in real offensive security scenarios.

```
┌───────────────────── WgpSec Agentic Ecosystem ─────────────────────┐
│                                                                     │
│  Knowledge ➜ Service ➜ Execution ➜ Evaluation                      │
│                                                                     │
│  AboutSecurity ──▶ context1337 ──▶ tchkiller ──▶ benchmark-platform │
│  (Knowledge Base)  (MCP Server)    (Pentest Agent)  (this repo)    │
│                                         ▲                           │
│                                    PoJun (General Solver)           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

| Project | Role |
|---------|------|
| [AboutSecurity](https://github.com/wgpsec/AboutSecurity) | Structured pentest knowledge base (Skills, Dic, Payload, Vuln) |
| [context1337](https://github.com/wgpsec/context1337) | MCP Server — turns AboutSecurity into a searchable API for AI agents |
| [tchkiller](https://github.com/wgpsec/tchkiller) | Autonomous pentest agent with multi-round decision-making and team collaboration |
| [benchmark-platform](https://github.com/wgpsec/benchmark-platform) | CTF challenge platform for evaluating agent offensive capabilities |
| PoJun | General-purpose AI problem-solving engine (private) |

## License

[MIT](LICENSE)

---

<a name="中文"></a>

# Benchmark Platform

CTF 靶场竞赛平台，用于安全能力评估。基于 Docker Compose 动态管理靶机实例，提供 Web UI 和 API 两种交互方式。

## 功能

- 靶机生命周期管理（启动/停止/健康检测）
- 多 Flag 支持（单题多个攻击路径）
- 难度分级与 Level Gate（逐级解锁）
- 实时状态展示（running / unhealthy / stopped）
- 提交记录与积分统计
- Hint 提示系统（带扣分机制）
- 镜像预构建/缓存页面（避免冷启动延迟）
- Apple Silicon (ARM64) 兼容

## 快速开始

### 环境要求

- Python >= 3.10
- Docker & Docker Compose
- sshpass（仅部署脚本需要）

### 安装

```bash
pip install -e .
```

### 启动服务

```bash
python -m benchmark_platform.server \
  --benchmark-folder ./challenges \
  --port 8088 \
  --public-accessible-host localhost
```

常用参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--benchmark-folder` | 靶机题目目录（可多次指定） | 必填 |
| `--benchmark-id` / `-i` | 只加载指定 ID 的题目 | 全部加载 |
| `--port` | 服务端口 | 8088 |
| `--public-accessible-host` | 靶机入口地址 | localhost |
| `--no-level-gate` | 禁用分级解锁 | false |

### 访问

启动后浏览器打开 `http://localhost:8088` 进入 Web UI。

## 项目结构

```
benchmark_platform/
├── server.py              # FastAPI 入口，API 路由
├── base.py                # 核心数据模型（Challenge, FlagState 等）
├── models/
│   └── benchmark.py       # Benchmark JSON schema
├── utils/
│   ├── challenge.py       # ChallengeManager（实例生命周期）
│   └── logger.py          # 结构化日志
├── web/
│   ├── routes.py          # Web UI 页面 & HTMX partial 路由
│   ├── context.py         # 模板上下文构建
│   ├── prebuild_manager.py # 镜像预构建管理器
│   ├── submission_store.py # 提交记录持久化
│   └── templates/         # Jinja2 模板
└── static/
    └── css/app.css

scripts/                   # 部署辅助脚本
challenges/                # 靶机题目源码（git ignored）
tests/                     # 测试
```

## API

### Web UI

| 路由 | 说明 |
|------|------|
| `GET /web/dashboard` | 仪表盘 |
| `GET /web/challenges` | 题目列表 |
| `GET /web/history` | 提交记录 |
| `GET /web/status` | 实例状态 |
| `GET /web/prebuild` | 镜像预热 |

### REST API

| 路由 | 说明 |
|------|------|
| `GET /api/challenges` | 获取所有题目 |
| `POST /api/start_challenge` | 启动靶机 `{code}` |
| `POST /api/stop_challenge` | 停止靶机 `{code}` |
| `POST /api/submit` | 提交 Flag `{code, flag}` |
| `POST /api/hint` | 获取提示 `{code}` |
| `POST /api/stop_all` | 停止所有实例 |
| `GET /api/challenges/{code}/progress` | 查询 Flag 进度 |

## 题目格式

每个题目是一个目录，包含：

```
XBEN-001-24/
├── docker-compose.yml    # 必须
├── benchmark.json        # 题目元数据（name, description, level, points）
├── benchmark.yaml        # 可选，多 flag 定义
├── .env                  # FLAG 环境变量
└── app/ mysql/ ...       # 应用代码
```

## 部署脚本

在 Mac 上预构建镜像并传输到 VM：

```bash
# 1. 构建所有 challenge 镜像
bash scripts/build_and_save_challenges.sh

# 2. 传输到 VM
VM_HOST=10.x.x.x VM_PORT=22 VM_USER=root VM_PASS=xxx \
  bash scripts/load_challenges_on_vm.sh

# 3. 在 VM 上预构建（如果未通过镜像传输）
bash scripts/prebuild_on_vm.sh
```

## 技术栈

- **后端**: FastAPI + Uvicorn
- **前端**: Jinja2 + HTMX + Alpine.js + Tailwind CSS (CDN)
- **容器**: Docker Compose
- **日志**: 结构化 JSONL

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
| PoJun | 通用 AI 求解引擎（私有） |

## 许可证

[MIT](LICENSE)
