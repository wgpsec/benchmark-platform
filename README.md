[中文文档](README.zh-CN.md) | English

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

## Screenshots

| Challenges | prebuild |
|-----------|------------|
| ![Challenges](.github/screenshots/challenges.png) | ![prebuild](.github/screenshots/prebuild.png) |

## Quick Start

### Requirements

- Python >= 3.10
- Docker & Docker Compose
- sshpass (deployment scripts only)

### Install

```bash
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

## Tech Stack

- **Backend**: FastAPI + Uvicorn
- **Frontend**: Jinja2 + HTMX + Alpine.js + Tailwind CSS (CDN)
- **Containers**: Docker Compose
- **Logging**: Structured JSONL

## References

- [xbow-engineering/validation-benchmarks](https://github.com/xbow-engineering/validation-benchmarks)
- [Neuro-Sploit/xbow-validation-benchmarks](https://github.com/Neuro-Sploit/xbow-validation-benchmarks)
- [Yeti-791/Tsec-Hackathon](https://github.com/Yeti-791/Tsec-Hackathon)

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
