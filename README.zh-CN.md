[English](README.md) | 中文文档

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

## 界面截图

| 题目列表 | 镜像预热 |
|--------|---------|
| ![Challenges](.github/screenshots/challenges.png) | ![prebuild](.github/screenshots/prebuild.png) |

## 快速开始

### 环境要求

- Python >= 3.10
- Docker & Docker Compose
- sshpass（仅部署脚本需要）

### 安装

```bash
pip install -e .
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

## 技术栈

- **后端**: FastAPI + Uvicorn
- **前端**: Jinja2 + HTMX + Alpine.js + Tailwind CSS (CDN)
- **容器**: Docker Compose
- **日志**: 结构化 JSONL

## 参考项目

- [xbow-engineering/validation-benchmarks](https://github.com/xbow-engineering/validation-benchmarks)
- [Neuro-Sploit/xbow-validation-benchmarks](https://github.com/Neuro-Sploit/xbow-validation-benchmarks)
- [Yeti-791/Tsec-Hackathon](https://github.com/Yeti-791/Tsec-Hackathon)

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
