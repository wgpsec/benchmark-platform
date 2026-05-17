[中文文档](README.zh-CN.md) | English

# Benchmark Platform

A CTF challenge platform for security capability evaluation. Dynamically manages challenge instances via Docker Compose, with both a Web UI and REST API interface.

## Features

- Challenge lifecycle management (start / stop / health check)
- **Dynamic Flag injection** — each instance gets a unique `flag{uuid}` at runtime, never baked into images
- **Challenge Store** — browse, download, and import challenges from GitHub Releases with China mirror acceleration
- **Hot-reload** — newly downloaded challenges are discoverable without server restart
- Multi-flag support (multiple attack paths per challenge)
- Difficulty tiering with Level Gate (progressive unlock)
- Real-time status display (running / unhealthy / stopped)
- Submission history & scoring (persisted across restarts)
- Hint system (with point deduction)
- Image pre-build / cache page (avoid cold-start delays, **selective build support**)
- Team management & multi-team scoring
- Runtime directory isolation (configurable via Web UI)
- **MCP Server** — Streamable HTTP endpoint for AI Agent integration (Claude Code, LangChain, openai-agents, etc.)
- **Web UI Authentication** — cookie-based login with admin/observer roles; admin token auto-generated or user-defined
- Apple Silicon (ARM64) compatibility

## Screenshots

| Dashboard | Challenges |
|-----------|-----------|
| ![Dashboard](.github/screenshots/dashboard.png) | ![Challenges](.github/screenshots/challenges.png) |

| Challenge Store | Prebuild |
|----------------|----------|
| ![Store](.github/screenshots/store.png) | ![Prebuild](.github/screenshots/prebuild.png) |

## Quick Start

### Requirements

- Python >= 3.10
- Docker & Docker Compose
- sshpass (deployment scripts only)

### Install

```bash
python3 -m venv venv

source venv/bin/activate

pip install -e .
```

### Prepare Challenge Data

Start the platform and navigate to **"靶场管理" (Challenge Store)** in the Web UI sidebar to browse and download challenges.

Alternatively, set up manually:

```bash
git clone https://github.com/wgpsec/benchmark-challenges /tmp/benchmarks
mkdir -p challenges
cp -r /tmp/benchmarks/xbow challenges/xbow
cp -r /tmp/benchmarks/custom challenges/custom
rm -rf /tmp/benchmarks
```

### Run

```bash
python3 -m benchmark_platform.server \
  --benchmark-folder ./challenges \
  --port 8088 \
  --public-accessible-host localhost
```

Options:

| Flag | Description | Default |
|------|-------------|---------|
| `--benchmark-folder` | Challenge directory (can be repeated) | required |
| `--benchmark-id` / `-i` | Load only specific IDs | all |
| `--challenges-dir` | Root directory for store downloads | `./challenges` |
| `--admin-token` | Admin token for Web UI login (random if omitted) | random |
| `--host` | Host to bind to | `0.0.0.0` |
| `--port` | Server port | 8088 |
| `--public-accessible-host` | Public hostname for challenges | localhost |
| `--no-level-gate` | Disable level-based unlock | false |

The `--admin-token` can also be set via the `ADMIN_TOKEN` environment variable. On startup the server prints the active admin token to the console.

### Access

Open `http://localhost:8088` in your browser. You will be redirected to the login page — enter the admin token printed in the console to get full access. Team observers log in with their own Agent-Token and see a read-only scoreboard.

## Project Structure

```
benchmark_platform/
├── server.py              # FastAPI entry, API routes
├── base.py                # Core models (Challenge, FlagState, etc.)
├── mcp_server.py          # MCP Server (5 tools via Streamable HTTP)
├── auth.py                # Agent-Token authentication
├── db.py                  # SQLite persistence (teams, progress, settings)
├── models/
│   └── benchmark.py       # Benchmark JSON schema
├── utils/
│   ├── challenge.py       # ChallengeManager (instance lifecycle, dynamic flag injection)
│   └── logger.py          # Structured logging
├── web/
│   ├── routes.py          # Web UI page & HTMX partial routes
│   ├── auth_middleware.py # Cookie-based session auth (admin/observer roles)
│   ├── context.py         # Template context builders
│   ├── prebuild_manager.py # Image pre-build manager
│   ├── submission_store.py # Submission persistence
│   ├── store.py           # Challenge store (GitHub Releases download)
│   └── templates/         # Jinja2 templates
└── static/
    └── css/app.css

scripts/                   # Deployment helper scripts
challenges/                # Challenge source code (git ignored)
runtime/                   # Running instance copies (git ignored)
tests/                     # Tests
```

## API

### Web UI

| Route | Description |
|-------|-------------|
| `GET /web/login` | Login page |
| `GET /web/scoreboard` | Observer scoreboard (read-only) |
| `GET /web/dashboard` | Dashboard |
| `GET /web/challenges` | Challenge list |
| `GET /web/history` | Submission history |
| `GET /web/status` | Instance status |
| `GET /web/store` | Challenge store (download / import) |
| `GET /web/prebuild` | Image pre-build |
| `GET /web/teams` | Team management |
| `GET /web/settings` | Platform settings |

### REST API

All endpoints require `Agent-Token` header. Endpoints marked with 🔒 require the admin (default team) token.

| Route | Description |
|-------|-------------|
| `GET /api/challenges` | List all challenges |
| `POST /api/start_challenge` | Start instance `{code}` |
| `POST /api/stop_challenge` | Stop instance `{code}` |
| `POST /api/submit` | Submit flag `{code, flag}` |
| `POST /api/hint` | Get hint `{code}` |
| `GET /api/challenges/{code}/progress` | Query flag progress |
| `POST /api/stop_all` | 🔒 Stop all instances |
| `POST /api/challenges/reload` | 🔒 Hot-reload newly downloaded challenges |
| `POST /api/start_level` | 🔒 Start all challenges at a level |
| `POST /api/stop_level` | 🔒 Stop all challenges at a level |
| `GET /api/instance_statuses` | 🔒 Batch query instance statuses |

### Store API (🔒 Admin only)

| Route | Description |
|-------|-------------|
| `GET /api/store/manifest` | Fetch remote challenge manifest |
| `POST /api/store/download` | Download a challenge by ID |
| `POST /api/store/download-all` | Download all challenges in a category |
| `POST /api/store/delete` | Delete a downloaded challenge |
| `POST /api/store/import` | Import a local zip file |

### Prebuild API (🔒 Admin only)

| Route | Description |
|-------|-------------|
| `POST /api/prebuild/start` | Start image pre-build (supports selective `{codes: [...]}`) |
| `POST /api/prebuild/stop` | Stop pre-build |
| `GET /api/prebuild/status` | Query pre-build progress |
| `POST /api/prebuild/remove` | Remove a pre-built image |
| `POST /api/prebuild/remove_batch` | Remove selected pre-built images `{codes: [...]}` |
| `POST /api/prebuild/remove_all` | Remove all pre-built images |

### MCP Server

The platform exposes an MCP (Model Context Protocol) endpoint at `/mcp/` using Streamable HTTP transport, allowing AI agents to interact with challenges directly.

**Tools:**

| Tool | Description | Parameters |
|------|-------------|------------|
| `list_challenges` | Get challenge list with team progress | — |
| `start_challenge` | Start a challenge instance | `code` |
| `stop_challenge` | Stop a running instance | `code` |
| `submit_flag` | Submit flag answer | `code`, `flag` |
| `view_hint` | View challenge hint (10% score penalty) | `code` |

**Authentication:** `Authorization: Bearer <agent_token>` header.

**Claude Code example:**

```bash
claude mcp add benchmark-platform \
  --transport http \
  --header "Authorization: Bearer <YOUR_TOKEN>" \
  http://<SERVER_HOST>:8088/mcp/
```

**JSON config (Cursor, Cline, Windsurf, etc.):**

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

## Agent Integration

The platform supports two integration methods for AI agents:

1. **MCP (recommended)** — Connect via Streamable HTTP at `/mcp/`, AI agents call tools directly without writing HTTP code. See [MCP Server](#mcp-server) section above.

2. **REST API** — Standard HTTP endpoints at `/api/*`. Authenticate with `Agent-Token: <token>` header. See [REST API](#rest-api) section above.

For complete API/MCP protocol documentation and integration examples (LangChain, openai-agents, Python native), see the [Tsec-Hackathon documentation](https://github.com/Yeti-791/Tsec-Hackathon/tree/main/%E7%AC%AC%E4%BA%8C%E5%B1%8A%E6%99%BA%E8%83%BD%E6%B8%97%E9%80%8F%E9%BB%91%E5%AE%A2%E6%9D%BE).

## Challenge Format

Each challenge is a directory containing:

```
XBEN-001-24/
├── docker-compose.yml    # Required (services read FLAG from environment)
├── benchmark.json        # Metadata (name, description, level, points)
├── benchmark.yaml        # Optional, multi-flag definitions
├── .env                  # FLAG placeholder (replaced at runtime with dynamic flag)
└── app/ mysql/ ...       # Application code
```

The platform injects a unique `flag{uuid}` into each instance at startup — challenge source code should read the flag from the `FLAG` environment variable rather than hardcoding it.

> **Contributing challenges:** This repo is the platform only. Challenge source code lives in [benchmark-challenges](https://github.com/wgpsec/benchmark-challenges). To add or modify challenges, submit PRs there.

## Tech Stack

- **Backend**: FastAPI + Uvicorn
- **Frontend**: Jinja2 + HTMX + Alpine.js + Tailwind CSS (CDN)
- **Containers**: Docker Compose
- **Logging**: Structured JSONL

## References

- [xbow-engineering/validation-benchmarks](https://github.com/xbow-engineering/validation-benchmarks)
- [Neuro-Sploit/xbow-validation-benchmarks](https://github.com/Neuro-Sploit/xbow-validation-benchmarks)
- [Yeti-791/Tsec-Hackathon](https://github.com/Yeti-791/Tsec-Hackathon)
- [Cyberdefense/GOAD](https://github.com/Orange-Cyberdefense/GOAD)
- [dockur/windows](https://github.com/dockur/windows)

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
| [benchmark-challenges](https://github.com/wgpsec/benchmark-challenges) | Challenge data repository — packed & distributed via GitHub Releases |
| PoJun | General-purpose AI problem-solving engine (private) |

## FAQ

### "all predefined address pools have been fully subnetted"

When starting many challenges simultaneously, Docker may run out of network address space. This is because Docker allocates a `/16` subnet per network by default, which limits the total number of networks.

**Fix:** Add `default-address-pools` to your Docker daemon config (Docker Desktop → Settings → Docker Engine):

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

Click **Apply & Restart**. This allocates `/24` per network (254 IPs each, more than enough for a challenge), allowing 4000+ concurrent networks.

## License

[MIT](LICENSE)
