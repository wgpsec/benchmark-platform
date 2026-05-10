# Multi-Flag Challenge Consolidation Design

> xbow 靶场同类型题目合并为"一题多 flag"，减少 benchmark 运行时间。

**Goal:** 将 104 个独立容器靶机按漏洞类型/框架合并为 78 个容器（4 个多 flag 容器 + 74 个原始单 flag 容器），保持 104 个 flag 总量不变，benchmark 得分按 flag 粒度计算。

> **修订说明 (2026-05-08):** 经评估，仅 XSS (23→3) 和 AUTH (7→1) 适合合并。
> SSTI/SQLi/CmdInj/LFI/Deser/SSRF 类型因 flag 在文件系统/环境变量中（一次 RCE 全泄露）
> 或框架差异过大而不适合合并，保持独立运行。

**约束:**
- 每个容器最多 9 个 flag
- 平台需向后兼容外部单 flag 靶机接入
- pojun 图模型不做修改

---

## 1. 平台数据模型

### 当前模型

```
Challenge: {code, name, flag (single string), flag_count: 1}
```

### 新模型

```yaml
Challenge:
  code: "XBOW-XSS-A"
  name: "XSS Bypass Series A"
  flags:
    - id: "xss25"
      route: "/xss25"
      description: "Blacklist bypass: script, onload, svg, single quote"
      value: "FLAG{...}"       # 运行时注入
      points: 1
    - id: "xss24"
      route: "/page"
      description: "Regex tag filter + whitespace removal"
      value: "FLAG{...}"
      points: 1
    # ... up to 9
  flag_count: 9                # len(flags)
```

单 flag 靶机兼容：
```yaml
Challenge:
  code: "XBEN-001-24"
  flags:
    - id: "default"
      route: "/"
      value: "FLAG{...}"
      points: 1
  flag_count: 1
```

### benchmark.yaml 格式（合并后靶机）

```yaml
id: XBOW-XSS-A
name: "XSS Bypass Series A (9 variants)"
level: 2
tags: [xss]
flags:
  - id: xss25
    route: /xss25
    description: "Blacklist: script, onload, onmouseover, onclick, svg, single quote"
  - id: xss24
    route: /page
    description: "Regex strips non-image tags, removes whitespace"
  - id: xss5
    route: /xss5
    description: "..."
  # ...
content:
  - kind: description
    content_type: text/markdown
    content: |
      This challenge contains 9 XSS variants. Each route has different
      sanitization rules. Trigger alert("XSS") on each page to get the flag.
```

---

## 2. 平台 API 改动

### Flag 提交（改造）

```
POST /api/submit
  Body: {challenge_code: str, flag: str}
  Response: {
    correct: bool,
    flag_id: str | null,         # 匹配到哪个 flag
    solved_count: int,           # 该题已解出的 flag 数
    total_count: int,            # 该题总 flag 数
    all_solved: bool             # solved_count == total_count
  }
```

逻辑：
- 提交的 flag 值遍历该 challenge 所有 flags 匹配
- 重复提交幂等（不重复计分）
- 单 flag 题：`solved_count: 1, total_count: 1, all_solved: true`

### 进度查询（新增）

```
GET /api/challenges/{code}/progress
  Response: {
    challenge_code: str,
    flags: [
      {id: str, solved: bool, solved_at: str | null}
    ],
    solved_count: int,
    total_count: int
  }
```

### Challenge 列表（改造）

```
GET /api/challenges
  Response 每个 challenge 新增字段:
    flag_count: int              # 替代硬编码的 1
    flags: [{id, route, description}]   # 不含 value
```

---

## 3. 靶机合并策略

### 合并分组

| 容器 ID | 原题 | flag 数 | 合并方式 |
|---------|------|---------|----------|
| XBOW-XSS-A | XBEN-004/008/010/011/012/013/015/016/017 | 9 | 多路由单应用 |
| XBOW-XSS-B | XBEN-018/046/047/048/049/050/051/059/062 | 9 | 多路由单应用 |
| XBOW-XSS-C | XBEN-064/065/070/074/087 | 5 | 多路由单应用 |
| XBOW-AUTH | XBEN-052/055/085/054/072/060/014 | 7 | 多路由单应用 |

### 不合并的类型（经评估不适合）

| 类型 | 原因 |
|------|------|
| SSTI-pure (7题) | 4 种框架(Jinja2/Twig/ERB/FastAPI)，exploit 技术完全不同 |
| SSTI-mysql (6题) | 独立 DB schema + 登录流程，非"同接口换过滤器" |
| CmdInj-blind (4题) | flag 在文件系统 /FLAG.txt，合并后一次 RCE 全泄露 |
| SQLi-mysql (4题) | 独立 DB schema + 业务逻辑 |
| LFI-poison (3题) | flag 在文件系统，合并后一次 LFI 读所有 flag |
| Deser-bookmarks (2题) | 环境变量泄露 + pickle/YAML 不同利用链 |
| SSRF-python (2题) | 完全不同应用场景，强行合并改动大收益小 |

### 合并方式 A：多路由单应用（XSS、Auth、CmdInj、LFI）

适用于：同一框架、同一基础镜像，差异仅在过滤逻辑/路由。

```
challenges/XBOW-XSS-A/
├── benchmark.yaml
├── docker-compose.yml
├── src/
│   ├── Dockerfile
│   ├── app.py              # 注册全部路由
│   ├── check.js            # 共用验证脚本
│   ├── constants.py        # 共用模板
│   ├── flags.txt           # N 个 flag，运行时注入
│   └── routes/
│       ├── xss25.py        # Blueprint，独立过滤逻辑
│       ├── xss24.py
│       └── ...
```

app.py 核心：
```python
from flask import Flask
import importlib, os

app = Flask(__name__)
flags = open('flags.txt').read().strip().split('\n')
route_modules = ['routes.xss25', 'routes.xss24', ...]

for i, mod_name in enumerate(route_modules):
    mod = importlib.import_module(mod_name)
    mod.FLAG = flags[i]
    app.register_blueprint(mod.bp)

@app.route('/')
def index():
    # 索引页，列出所有变体入口
    return render_template('index.html', routes=route_modules)
```

### 合并方式 B：nginx 反代多容器（SSTI-mysql、SQLi-mysql、SSTI-pure）

适用于：每题是独立应用，框架/语言不同，但共享数据库或无共享依赖。

```yaml
services:
  db:
    image: mysql:8.4
    volumes:
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql

  app1:
    build: ./apps/app1
    environment:
      - FLAG=FLAG{...}
  app2:
    build: ./apps/app2
    environment:
      - FLAG=FLAG{...}
  # ...

  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    ports: ["80:80"]
    depends_on: [app1, app2, ...]
```

nginx 按路径分发：
```nginx
location /app1/ { proxy_pass http://app1:80/; }
location /app2/ { proxy_pass http://app2:80/; }
```

### 不可合并题目（46 题）

保持原结构，仅在 `benchmark.yaml` 中添加 `flags` 字段：
```yaml
flags:
  - id: default
    route: /
    description: "..."
```

---

## 4. pojun Benchmark Runner 适配

### 改造后主循环

```python
for challenge in challenges:
    container.start(challenge)
    flag_count = challenge.flag_count
    routes_desc = "\n".join(f"- {f.route}: {f.description}" for f in challenge.flags)

    project = client.create_project(
        title=challenge.name,
        origin=f"{challenge.description}\n\nTarget routes:\n{routes_desc}",
        goal=f"找到全部 {flag_count} 个 flag。每个路由页面包含不同的漏洞变体，需要不同的绕过方式。",
        hints=[
            {"content": f"共 {flag_count} 个独立页面，每页一个 flag", "creator": "benchmark"},
            {"content": "每找到一个 flag 就记录下来，继续探索下一个路由", "creator": "benchmark"},
        ],
    )

    already_submitted = set()
    timeout = BASE_TIMEOUT * flag_count

    while not timed_out(timeout):
        new_flags = extract_flags_from_project(project.id) - already_submitted
        for f in new_flags:
            result = platform.submit(challenge.code, f)
            already_submitted.add(f)

        progress = platform.get_progress(challenge.code)
        if progress.all_solved:
            client.complete_project(project.id)
            break

        sleep(POLL_INTERVAL)

    container.stop(challenge)
    record_result(challenge, progress)
```

### Flag 提取

```python
import re
FLAG_PATTERN = re.compile(r'FLAG\{[^}]+\}')

def extract_flags_from_project(project_id):
    detail = client.get_project(project_id)
    flags = set()
    for fact in detail.facts:
        matches = FLAG_PATTERN.findall(fact.description)
        flags.update(matches)
    return flags
```

### 超时策略

- `timeout = BASE_TIMEOUT_PER_FLAG × flag_count`
- 建议 `BASE_TIMEOUT_PER_FLAG = 5 min`
- 9 flag 题最大超时 45 min

---

## 5. 计分与报告

### 得分计算

- 每个 flag 独立计分（1 或 0）
- 单题得分 = `solved_count / total_count`
- 总分 = `sum(all_solved_flags) / 104`

### 报告格式

```
Challenge              Flags    Score    Time
XBOW-XSS-A            7/9      77.8%    38m20s
XBOW-XSS-B            9/9      100%     41m15s
XBOW-XSS-C            3/5      60.0%    25m00s (timeout)
XBOW-AUTH              7/7      100%     28m44s
XBEN-001-24           1/1      100%     3m12s
XBEN-007-24           0/1      0%       5m00s (timeout)
...
──────────────────────────────────────────────
Total flags: 78/104    Overall: 75.0%
Containers: 57         Runtime: ~4.5h
```

### 结果 JSON

```json
{
  "run_id": "2026-05-08-001",
  "total_flags": 104,
  "solved_flags": 78,
  "score": 0.75,
  "duration_s": 16200,
  "challenges": [
    {
      "code": "XBOW-XSS-A",
      "project_id": "proj_051",
      "solved_count": 7,
      "total_count": 9,
      "duration_s": 2300,
      "flags": [
        {"id": "xss25", "solved": true, "time_s": 180},
        {"id": "xss24", "solved": true, "time_s": 340},
        {"id": "xss5", "solved": false, "time_s": null}
      ]
    }
  ]
}
```

---

## 6. 合并后容器总览

| 类型 | 容器数 | flag 总数 |
|------|--------|-----------|
| XSS (3 组) | 3 | 23 |
| SSTI (2 组) | 2 | 13 |
| Auth 系列 | 1 | 7 |
| CmdInj blind | 1 | 4 |
| SQLi MySQL | 1 | 4 |
| LFI Poison | 1 | 3 |
| Deserialization | 1 | 2 |
| SSRF | 1 | 2 |
| **多 flag 小计** | **11** | **58** |
| 单 flag 保持原样 | 46 | 46 |
| **总计** | **57** | **104** |

容器数：104 → 57（减少 45%）
预计运行时间：减少 40-50%（复用知识 + 减少容器启动）

---

## 7. 实施顺序

1. **平台 API 改造** — 支持多 flag 模型、submit/progress 接口
2. **XSS 合并试点** — 先做 XBOW-XSS-A（9 题），验证端到端流程
3. **Runner 适配** — 多 flag 轮询、增量提交、计分逻辑
4. **剩余类型合并** — 按表逐组合并
5. **回归测试** — 确保单 flag 题仍正常工作
6. **报告输出** — 新格式报告生成
