# Challenge Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Web UI "靶场管理" page that fetches a challenge manifest from GitHub Release and downloads individual challenge zips on demand.

**Architecture:** New `store.py` module handles GitHub Release API interactions (fetch manifest, download zip, extract). Web UI page uses Alpine.js to display available challenges and trigger downloads via API. No new dependencies — uses stdlib `urllib` and `zipfile`.

**Tech Stack:** FastAPI, Jinja2, Alpine.js, Python stdlib (urllib.request, zipfile, json)

---

## File Structure

```
benchmark_platform/
├── web/
│   ├── store.py                    # NEW: Challenge store logic (fetch manifest, download, extract)
│   ├── routes.py                   # MODIFY: Add store page route
│   └── templates/
│       └── pages/store.html        # NEW: Store page template
├── server.py                       # MODIFY: Add store API endpoints
└── web/templates/components/
    └── sidebar.html                # MODIFY: Add nav item
```

---

### Task 1: Challenge Store Backend Module

**Files:**
- Create: `benchmark_platform/web/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_store.py
import json
import zipfile
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from benchmark_platform.web.store import ChallengeStore


def test_parse_manifest():
    raw = json.dumps({
        "version": "2026-05-11",
        "challenges": [
            {"name": "XBEN-001-24", "category": "xbow", "asset": "xbow--XBEN-001-24.zip", "description": "SSH Injection", "difficulty": "easy"}
        ]
    })
    store = ChallengeStore(challenges_dir=Path("/tmp/test_challenges"), repo="wgpsec/ctf-benchmarks", tag="latest")
    manifest = store._parse_manifest(raw)
    assert len(manifest["challenges"]) == 1
    assert manifest["challenges"][0]["name"] == "XBEN-001-24"


def test_is_downloaded(tmp_path):
    store = ChallengeStore(challenges_dir=tmp_path, repo="wgpsec/ctf-benchmarks", tag="latest")
    assert store.is_downloaded("xbow", "XBEN-001-24") is False
    (tmp_path / "xbow" / "XBEN-001-24").mkdir(parents=True)
    (tmp_path / "xbow" / "XBEN-001-24" / "docker-compose.yml").touch()
    assert store.is_downloaded("xbow", "XBEN-001-24") is True


def test_extract_zip(tmp_path):
    # Create a test zip with a file inside
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("docker-compose.yml", "version: '3'")
        zf.writestr("app/main.py", "print('hello')")

    store = ChallengeStore(challenges_dir=tmp_path, repo="wgpsec/ctf-benchmarks", tag="latest")
    dest = tmp_path / "xbow" / "XBEN-001-24"
    store._extract_zip(zip_path, dest)

    assert (dest / "docker-compose.yml").exists()
    assert (dest / "app" / "main.py").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'benchmark_platform.web.store'`

- [ ] **Step 3: Implement ChallengeStore**

```python
# benchmark_platform/web/store.py
from __future__ import annotations

import json
import shutil
import zipfile
import tempfile
import urllib.request
from pathlib import Path


GITHUB_RELEASE_URL = "https://github.com/{repo}/releases/download/{tag}/{asset}"
MANIFEST_URL = "https://github.com/{repo}/releases/download/{tag}/manifest.json"


class ChallengeStore:
    def __init__(self, challenges_dir: Path, repo: str = "wgpsec/ctf-benchmarks", tag: str = "latest"):
        self.challenges_dir = challenges_dir
        self.repo = repo
        self.tag = tag

    def fetch_manifest(self) -> dict:
        url = MANIFEST_URL.format(repo=self.repo, tag=self.tag)
        with urllib.request.urlopen(url, timeout=30) as resp:
            raw = resp.read().decode()
        return self._parse_manifest(raw)

    def _parse_manifest(self, raw: str) -> dict:
        return json.loads(raw)

    def is_downloaded(self, category: str, name: str) -> bool:
        target = self.challenges_dir / category / name / "docker-compose.yml"
        return target.exists()

    def download_challenge(self, category: str, name: str, asset: str) -> Path:
        url = GITHUB_RELEASE_URL.format(repo=self.repo, tag=self.tag, asset=asset)
        dest = self.challenges_dir / category / name

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            urllib.request.urlretrieve(url, tmp_path)
            self._extract_zip(tmp_path, dest)
        finally:
            tmp_path.unlink(missing_ok=True)

        return dest

    def _extract_zip(self, zip_path: Path, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/test_store.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add benchmark_platform/web/store.py tests/test_store.py
git commit -m "feat: add ChallengeStore module for remote challenge download"
```

---

### Task 2: Store API Endpoints

**Files:**
- Modify: `benchmark_platform/server.py`

- [ ] **Step 1: Add store API endpoints to server.py**

Add after the existing prebuild endpoints (around line 580):

```python
# -- Challenge Store API -------------------------------------------------------

@app.get("/api/store/manifest")
async def store_manifest():
    from benchmark_platform.web.store import ChallengeStore
    store = ChallengeStore(
        challenges_dir=Path(app.state.manager.benchmark_folders[0]).parent if app.state.manager else Path("challenges"),
    )
    try:
        manifest = store.fetch_manifest()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch manifest: {e}")
    # Annotate download status
    for ch in manifest.get("challenges", []):
        ch["downloaded"] = store.is_downloaded(ch["category"], ch["name"])
    return {"code": 0, "data": manifest}


@app.post("/api/store/download")
async def store_download(body: dict):
    from benchmark_platform.web.store import ChallengeStore
    category = body.get("category")
    name = body.get("name")
    asset = body.get("asset")
    if not all([category, name, asset]):
        raise HTTPException(status_code=400, detail="category, name, asset required")

    store = ChallengeStore(
        challenges_dir=Path(app.state.manager.benchmark_folders[0]).parent if app.state.manager else Path("challenges"),
    )
    try:
        store.download_challenge(category, name, asset)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Download failed: {e}")
    return {"code": 0, "message": f"{category}/{name} downloaded"}


@app.post("/api/store/download-all")
async def store_download_all():
    from benchmark_platform.web.store import ChallengeStore
    store = ChallengeStore(
        challenges_dir=Path(app.state.manager.benchmark_folders[0]).parent if app.state.manager else Path("challenges"),
    )
    try:
        manifest = store.fetch_manifest()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch manifest: {e}")

    results = []
    for ch in manifest.get("challenges", []):
        if store.is_downloaded(ch["category"], ch["name"]):
            results.append({"name": ch["name"], "status": "skipped"})
            continue
        try:
            store.download_challenge(ch["category"], ch["name"], ch["asset"])
            results.append({"name": ch["name"], "status": "ok"})
        except Exception as e:
            results.append({"name": ch["name"], "status": f"error: {e}"})
    return {"code": 0, "data": results}
```

- [ ] **Step 2: Verify server starts without error**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -c "from benchmark_platform.server import app; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add benchmark_platform/server.py
git commit -m "feat: add challenge store API endpoints (manifest, download, download-all)"
```

---

### Task 3: Store Web UI Page

**Files:**
- Create: `benchmark_platform/web/templates/pages/store.html`
- Modify: `benchmark_platform/web/routes.py`
- Modify: `benchmark_platform/web/templates/components/sidebar.html`

- [ ] **Step 1: Add page route in routes.py**

Add after the `page_teams` route:

```python
@web_router.get("/store")
async def page_store(request: Request):
    return _render(request, "pages/store.html", {"page": "store"})
```

- [ ] **Step 2: Add sidebar nav item**

In `sidebar.html`, add after the "队伍管理" link (before `</nav>`):

```html
    <a href="/web/store"
       class="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap
              {% if page == 'store' %}bg-gray-900 text-white{% else %}text-gray-600 hover:bg-gray-50 cursor-pointer{% endif %}">
      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"/>
      </svg>
      靶场管理
    </a>
```

- [ ] **Step 3: Create store.html page template**

```html
{% extends "base.html" %}
{% block title %}靶场管理 — Benchmark Platform{% endblock %}
{% block content %}
<div x-data="storePage()" x-init="init()">
  <!-- Header -->
  <div class="flex items-center justify-between mb-6">
    <div class="text-[13px] text-gray-500">
      可用靶场：<span x-text="challenges.length" class="font-medium text-gray-700">0</span> 个
      · 已下载：<span x-text="downloadedCount" class="font-medium text-emerald-600">0</span> 个
    </div>
    <div class="flex gap-2">
      <button @click="refreshManifest()"
              :disabled="loading"
              class="h-9 px-4 border border-gray-200 text-gray-700 text-[12px] font-medium rounded-lg hover:bg-gray-50 transition-colors cursor-pointer disabled:opacity-50">
        刷新列表
      </button>
      <button @click="downloadAll()"
              :disabled="loading"
              class="h-9 px-4 bg-gray-900 text-white text-[12px] font-medium rounded-lg hover:bg-gray-800 transition-colors cursor-pointer disabled:opacity-50">
        <span x-show="!downloading">全部下载</span>
        <span x-show="downloading">下载中...</span>
      </button>
    </div>
  </div>

  <!-- Error message -->
  <div x-show="error" class="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-[12px] text-red-700" x-text="error"></div>

  <!-- Loading -->
  <div x-show="loading && !challenges.length" class="text-center py-12 text-[12px] text-gray-500">
    正在获取靶场列表...
  </div>

  <!-- Category groups -->
  <template x-for="cat in categories" :key="cat">
    <div class="mb-6">
      <h3 class="text-[12px] font-semibold text-gray-500 uppercase tracking-wider mb-3 px-1" x-text="cat"></h3>
      <div class="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <table class="w-full">
          <thead class="bg-gray-50 border-b border-gray-100">
            <tr>
              <th class="px-4 py-3 text-left text-[12px] font-medium text-gray-500">名称</th>
              <th class="px-4 py-3 text-left text-[12px] font-medium text-gray-500">描述</th>
              <th class="px-4 py-3 text-left text-[12px] font-medium text-gray-500">难度</th>
              <th class="px-4 py-3 text-left text-[12px] font-medium text-gray-500 w-24">状态</th>
              <th class="px-4 py-3 text-left text-[12px] font-medium text-gray-500 w-20">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-100">
            <template x-for="ch in challengesByCategory(cat)" :key="ch.name">
              <tr class="hover:bg-gray-50 transition-colors">
                <td class="px-4 py-3 text-[12px] text-gray-900 font-medium" x-text="ch.name"></td>
                <td class="px-4 py-3 text-[12px] text-gray-600" x-text="ch.description || '-'"></td>
                <td class="px-4 py-3">
                  <span class="text-[11px] px-1.5 py-0.5 rounded"
                        :class="difficultyClass(ch.difficulty)"
                        x-text="ch.difficulty || '-'"></span>
                </td>
                <td class="px-4 py-3">
                  <span x-show="ch.downloaded" class="text-[11px] text-emerald-600 font-medium">已下载</span>
                  <span x-show="!ch.downloaded && !ch._downloading" class="text-[11px] text-gray-400">未下载</span>
                  <span x-show="ch._downloading" class="text-[11px] text-blue-500">下载中...</span>
                </td>
                <td class="px-4 py-3">
                  <button x-show="!ch.downloaded && !ch._downloading"
                          @click="downloadOne(ch)"
                          class="text-[11px] text-blue-600 hover:text-blue-800 cursor-pointer">下载</button>
                  <span x-show="ch.downloaded" class="text-[11px] text-gray-400">-</span>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>
  </template>
</div>

<script>
function storePage() {
  return {
    challenges: [],
    loading: false,
    downloading: false,
    error: '',
    get categories() {
      return [...new Set(this.challenges.map(c => c.category))].sort();
    },
    get downloadedCount() {
      return this.challenges.filter(c => c.downloaded).length;
    },
    challengesByCategory(cat) {
      return this.challenges.filter(c => c.category === cat);
    },
    difficultyClass(d) {
      const map = {
        easy: 'bg-emerald-50 text-emerald-700',
        medium: 'bg-amber-50 text-amber-700',
        hard: 'bg-red-50 text-red-700',
      };
      return map[d] || 'bg-gray-50 text-gray-600';
    },
    async init() {
      await this.refreshManifest();
    },
    async refreshManifest() {
      this.loading = true;
      this.error = '';
      try {
        const resp = await fetch('/api/store/manifest');
        const data = await resp.json();
        if (data.code !== 0) throw new Error(data.detail || 'Unknown error');
        this.challenges = data.data.challenges || [];
      } catch (e) {
        this.error = '获取靶场列表失败: ' + e.message;
      } finally {
        this.loading = false;
      }
    },
    async downloadOne(ch) {
      ch._downloading = true;
      try {
        const resp = await fetch('/api/store/download', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({category: ch.category, name: ch.name, asset: ch.asset})
        });
        const data = await resp.json();
        if (data.code !== 0) throw new Error(data.detail || 'Download failed');
        ch.downloaded = true;
      } catch (e) {
        this.error = ch.name + ' 下载失败: ' + e.message;
      } finally {
        ch._downloading = false;
      }
    },
    async downloadAll() {
      this.downloading = true;
      this.error = '';
      try {
        const resp = await fetch('/api/store/download-all', {method: 'POST'});
        const data = await resp.json();
        if (data.code !== 0) throw new Error(data.detail || 'Download failed');
        await this.refreshManifest();
      } catch (e) {
        this.error = '批量下载失败: ' + e.message;
      } finally {
        this.downloading = false;
      }
    }
  };
}
</script>
{% endblock %}
```

- [ ] **Step 4: Verify page loads**

Run: Start server and navigate to `http://localhost:8088/web/store`. Verify page renders (manifest fetch will fail since repo doesn't exist yet, but page should show error gracefully).

- [ ] **Step 5: Commit**

```bash
git add benchmark_platform/web/templates/pages/store.html benchmark_platform/web/routes.py benchmark_platform/web/templates/components/sidebar.html
git commit -m "feat: add challenge store Web UI page"
```

---

### Task 4: Update README

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`

- [ ] **Step 1: Update English README**

Replace the "Prepare Challenge Data" section with:

```markdown
### Prepare Challenge Data

Start the platform and navigate to **"靶场管理" (Challenge Store)** in the Web UI sidebar to browse and download challenges.

Alternatively, set up manually:

\`\`\`bash
git clone https://github.com/wgpsec/ctf-benchmarks /tmp/benchmarks
mkdir -p challenges
cp -r /tmp/benchmarks/xbow challenges/xbow
cp -r /tmp/benchmarks/custom challenges/custom
rm -rf /tmp/benchmarks
\`\`\`

Then start with multiple benchmark folders:

\`\`\`bash
python -m benchmark_platform.server \
  --benchmark-folder ./challenges/xbow \
  --benchmark-folder ./challenges/custom \
  --port 8088 \
  --public-accessible-host localhost
\`\`\`
```

- [ ] **Step 2: Update Chinese README**

Replace the "准备靶场题目" section with:

```markdown
### 准备靶场题目

启动平台后，在 Web UI 侧边栏点击 **「靶场管理」** 即可浏览并下载靶场题目。

也可以手动拉取：

\`\`\`bash
git clone https://github.com/wgpsec/ctf-benchmarks /tmp/benchmarks
mkdir -p challenges
cp -r /tmp/benchmarks/xbow challenges/xbow
cp -r /tmp/benchmarks/custom challenges/custom
rm -rf /tmp/benchmarks
\`\`\`

然后指定多个目录启动：

\`\`\`bash
python -m benchmark_platform.server \
  --benchmark-folder ./challenges/xbow \
  --benchmark-folder ./challenges/custom \
  --port 8088 \
  --public-accessible-host localhost
\`\`\`
```

- [ ] **Step 3: Commit**

```bash
git add README.md README.zh-CN.md
git commit -m "docs: update README with challenge store usage"
```

---

### Task 5: ctf-benchmarks GitHub Action (Incremental Pack)

**Files:**
- Create: (in new repo `wgpsec/ctf-benchmarks`) `.github/workflows/pack-challenges.yml`

- [ ] **Step 1: Create the workflow file**

```yaml
name: Pack & Publish Challenges

on:
  push:
    branches: [main]

permissions:
  contents: write

jobs:
  pack:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 2

      - name: Detect changed challenges
        id: detect
        run: |
          CHANGED=$(git diff --name-only HEAD~1 HEAD | grep -E '^(xbow|custom)/' | cut -d'/' -f1,2 | sort -u || true)
          echo "changed<<EOF" >> $GITHUB_OUTPUT
          echo "$CHANGED" >> $GITHUB_OUTPUT
          echo "EOF" >> $GITHUB_OUTPUT
          if [ -z "$CHANGED" ]; then
            echo "skip=true" >> $GITHUB_OUTPUT
          else
            echo "skip=false" >> $GITHUB_OUTPUT
          fi

      - name: Pack changed challenges
        if: steps.detect.outputs.skip == 'false'
        run: |
          mkdir -p dist
          while IFS= read -r dir; do
            [ -z "$dir" ] && continue
            CATEGORY=$(echo "$dir" | cut -d'/' -f1)
            NAME=$(echo "$dir" | cut -d'/' -f2)
            ASSET="${CATEGORY}--${NAME}.zip"
            echo "Packing $dir -> $ASSET"
            (cd "$dir" && zip -r "../../dist/$ASSET" .)
          done <<< "${{ steps.detect.outputs.changed }}"

      - name: Generate manifest.json
        run: |
          python3 - <<'PYEOF'
          import json, os
          from pathlib import Path
          from datetime import datetime, timezone

          challenges = []
          for category_dir in sorted(Path(".").iterdir()):
              if category_dir.name in ("xbow", "custom") and category_dir.is_dir():
                  for ch_dir in sorted(category_dir.iterdir()):
                      if not ch_dir.is_dir():
                          continue
                      meta = {}
                      benchmark_json = ch_dir / "benchmark.json"
                      if benchmark_json.exists():
                          with open(benchmark_json) as f:
                              meta = json.load(f)
                      challenges.append({
                          "name": ch_dir.name,
                          "category": category_dir.name,
                          "asset": f"{category_dir.name}--{ch_dir.name}.zip",
                          "description": meta.get("name", ""),
                          "difficulty": meta.get("difficulty", ""),
                      })

          manifest = {
              "version": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "repo": "wgpsec/ctf-benchmarks",
              "challenges": challenges,
          }

          os.makedirs("dist", exist_ok=True)
          with open("dist/manifest.json", "w") as f:
              json.dump(manifest, f, indent=2, ensure_ascii=False)

          print(f"Generated manifest with {len(challenges)} challenges")
          PYEOF

      - name: Create or update release
        if: steps.detect.outputs.skip == 'false'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          # Ensure the 'latest' release exists
          gh release view latest >/dev/null 2>&1 || gh release create latest --title "Challenge Assets" --notes "Auto-published challenge zip archives"

          # Upload changed zips (overwrite existing)
          for f in dist/*.zip; do
            [ -f "$f" ] && gh release upload latest "$f" --clobber
          done

          # Always upload manifest
          gh release upload latest dist/manifest.json --clobber

      - name: Upload manifest only (no challenge changes)
        if: steps.detect.outputs.skip == 'true'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          echo "No challenge changes detected, skipping pack."
```

- [ ] **Step 2: Create repo README.md**

```markdown
# CTF Benchmarks

Challenge data repository for [benchmark-platform](https://github.com/wgpsec/benchmark-platform).

## Structure

```
xbow/          # Challenges from xbow-validation-benchmarks
custom/        # Custom challenges (XSS, Auth, etc.)
```

## Usage

This repo is consumed by benchmark-platform's Challenge Store feature. Challenges are automatically packaged and published as GitHub Release assets on each push.

## Adding a Challenge

1. Create a directory under the appropriate category: `xbow/XBEN-XXX-24/` or `custom/MY-CHALLENGE/`
2. Include at minimum: `docker-compose.yml`, `benchmark.json`, `.env`
3. Push to main — the GitHub Action will package and publish it automatically

## License

[MIT](LICENSE)
```

- [ ] **Step 3: Commit and push (in ctf-benchmarks repo)**

```bash
git add .github/workflows/pack-challenges.yml README.md
git commit -m "ci: add incremental challenge pack & publish workflow"
git push
```

---

## Self-Review

**Spec coverage:**
- ✅ ctf-benchmarks directory structure (xbow/ + custom/)
- ✅ GitHub Action with incremental detection
- ✅ manifest.json generation with metadata extraction
- ✅ Platform Web UI page for browsing and downloading
- ✅ API endpoints (manifest, download single, download-all)
- ✅ README updates for both repos

**Placeholder scan:** None found.

**Type consistency:** `ChallengeStore` methods match across Task 1 (definition) and Task 2 (usage in endpoints). `manifest.json` schema consistent between Action output and platform parsing.
