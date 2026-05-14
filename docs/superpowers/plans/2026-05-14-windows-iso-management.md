# Windows ISO Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the platform to automatically inject a local Windows Server 2022 ISO into dockur/windows-based challenges, blocking start without config and showing a timing hint on the frontend.

**Architecture:** New `win2022_iso_path` setting stored via existing KV system, read at challenge start time. Challenge model gets a `requires_windows_iso` bool detected from docker-compose.yml at discovery time. Startup injection appends a read-only bind mount to the runtime compose YAML before `docker compose up -d`.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, PyYAML, SQLite (settings KV), Jinja2 + Alpine.js (frontend)

---

## File Map

| File | Responsibility | Action |
|------|---------------|--------|
| `benchmark_platform/base.py` | Challenge model | Add `requires_windows_iso: bool = False` field |
| `benchmark_platform/utils/challenge.py` | ChallengeManager | Detect dockur in compose; inject ISO mount at start |
| `benchmark_platform/server.py` | API routes | Add GET/POST `/api/settings/win_iso` |
| `benchmark_platform/web/context.py` | Template context | Pass `requires_windows_iso` to card dict |
| `benchmark_platform/web/templates/pages/settings.html` | Settings UI | Add Windows ISO card |
| `benchmark_platform/web/templates/components/challenge_card.html` | Challenge card | Add amber timing hint |
| `tests/test_web_context.py` | Tests | Add test for `requires_windows_iso` in card |
| `tests/test_iso_injection.py` | Tests | Test ISO detection + injection logic |

---

### Task 1: Add `requires_windows_iso` field to Challenge model

**Files:**
- Modify: `benchmark_platform/base.py:42-43`

- [ ] **Step 1: Add the field**

In `benchmark_platform/base.py`, add `requires_windows_iso: bool = False` to the Challenge model, after the `unsupported_reason` field:

```python
class Challenge(BaseModel):
    challenge_code: str
    difficulty: Difficulty
    points: int
    hint_viewed: bool
    solved: bool
    target_info: TargetInfo
    flag_states: list[FlagState] = []
    emulated: bool = False
    unsupported: bool = False
    unsupported_reason: str = ""
    requires_windows_iso: bool = False
    _benchmark_id: str | None = PrivateAttr(default=None)
    _runtime_dir: Path | None = PrivateAttr(default=None)
```

- [ ] **Step 2: Verify no regressions**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -m pytest tests/ -x -q`
Expected: All existing tests pass (new field has default value, so no impact)

- [ ] **Step 3: Commit**

```bash
git add benchmark_platform/base.py
git commit -m "feat: add requires_windows_iso field to Challenge model"
```

---

### Task 2: Detect dockur images during challenge discovery

**Files:**
- Modify: `benchmark_platform/utils/challenge.py:288-301` (`_create_challenge`)
- Modify: `benchmark_platform/utils/challenge.py:420-434` (`_restore_challenge`)
- Create: `tests/test_iso_injection.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_iso_injection.py`:

```python
"""Tests for Windows ISO detection and injection."""
import tempfile
from pathlib import Path

import yaml

from benchmark_platform.utils.challenge import ChallengeManager


def _write_compose(path: Path, services: dict) -> None:
    """Write a docker-compose.yml with given services dict."""
    (path / "docker-compose.yml").write_text(yaml.dump({"services": services}))


def test_detect_requires_windows_iso():
    """Challenge with dockurr/windows image should set requires_windows_iso=True."""
    compose_data = {
        "services": {
            "dc": {"image": "dockurr/windows", "environment": ["VERSION=2022"]},
            "web": {"build": {"context": "./src/web"}, "ports": ["80:80"]},
        }
    }
    result = ChallengeManager._detect_requires_windows_iso(compose_data)
    assert result is True


def test_detect_no_windows_iso():
    """Challenge without dockur image should not require ISO."""
    compose_data = {
        "services": {
            "web": {"build": {"context": "./src/web"}, "ports": ["80:80"]},
            "db": {"image": "mysql:8.0"},
        }
    }
    result = ChallengeManager._detect_requires_windows_iso(compose_data)
    assert result is False


def test_detect_case_insensitive():
    """Detection should be case-insensitive for dockur substring."""
    compose_data = {
        "services": {
            "vm": {"image": "Dockur/Windows"},
        }
    }
    result = ChallengeManager._detect_requires_windows_iso(compose_data)
    assert result is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -m pytest tests/test_iso_injection.py -x -v`
Expected: FAIL with `AttributeError: type object 'ChallengeManager' has no attribute '_detect_requires_windows_iso'`

- [ ] **Step 3: Implement the detection helper**

In `benchmark_platform/utils/challenge.py`, add a static method to the `ChallengeManager` class (before `_create_challenge`):

```python
@staticmethod
def _detect_requires_windows_iso(compose_data: dict) -> bool:
    """Check if any service uses a dockur/windows image."""
    for svc in compose_data.get("services", {}).values():
        image = svc.get("image", "")
        if "dockur" in image.lower():
            return True
    return False
```

- [ ] **Step 4: Wire detection into `_create_challenge`**

In `_create_challenge()`, after the `is_unsupported` / `unsupported_reason` block (around line 287) and before the `challenge = Challenge(...)` constructor call, add:

```python
requires_win_iso = self._detect_requires_windows_iso(data)
```

Then pass it to the Challenge constructor:

```python
challenge = Challenge(
    challenge_code=challenge_id,
    difficulty=_level_map[bm.level],
    points=bm.points,
    hint_viewed=False,
    solved=False,
    target_info=TargetInfo(
        ip=self.public_accessible_host, port=allocated_ports,
    ),
    flag_states=flag_states,
    emulated=is_emulated,
    unsupported=is_unsupported,
    unsupported_reason=unsupported_reason,
    requires_windows_iso=requires_win_iso,
)
```

- [ ] **Step 5: Wire detection into `_restore_challenge`**

In `_restore_challenge()`, after the `is_unsupported` block (around line 418) and before the `challenge = Challenge(...)` constructor call, add:

```python
requires_win_iso = self._detect_requires_windows_iso(data)
```

Then pass it to the Challenge constructor:

```python
challenge = Challenge(
    challenge_code=challenge_code,
    difficulty=_level_map[bm.level],
    points=bm.points,
    hint_viewed=False,
    solved=False,
    target_info=TargetInfo(ip=self.public_accessible_host, port=ports),
    flag_states=flag_states,
    emulated=is_emulated,
    unsupported=is_unsupported,
    unsupported_reason=unsupported_reason,
    requires_windows_iso=requires_win_iso,
)
```

- [ ] **Step 6: Run tests**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -m pytest tests/test_iso_injection.py tests/test_web_context.py -x -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add benchmark_platform/utils/challenge.py tests/test_iso_injection.py
git commit -m "feat: detect dockur/windows in compose to set requires_windows_iso"
```

---

### Task 3: ISO injection in `start_challenge_instance`

**Files:**
- Modify: `benchmark_platform/utils/challenge.py:489-513` (`start_challenge_instance`)
- Modify: `tests/test_iso_injection.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_iso_injection.py`:

```python
import os
import json
import shutil


def test_inject_iso_mount_into_compose(tmp_path):
    """ISO bind mount should be appended to dockur service volumes."""
    compose_data = {
        "services": {
            "dc": {
                "image": "dockurr/windows",
                "volumes": ["dc-data:/storage"],
            },
            "web": {
                "build": {"context": "./src/web"},
                "ports": ["80:80"],
            },
        }
    }
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(yaml.dump(compose_data))

    iso_path = tmp_path / "win2022.iso"
    iso_path.write_bytes(b"fake iso content")

    ChallengeManager._inject_windows_iso(compose_path, str(iso_path))

    result = yaml.safe_load(compose_path.read_text())
    dc_volumes = result["services"]["dc"]["volumes"]
    assert f"{iso_path}:/storage/custom.iso:ro" in dc_volumes
    assert len(result["services"]["web"].get("volumes", [])) == 0


def test_inject_iso_skips_non_dockur(tmp_path):
    """Non-dockur services should not get ISO mount."""
    compose_data = {
        "services": {
            "web": {
                "image": "nginx:latest",
                "volumes": ["/data:/usr/share/nginx/html"],
            },
        }
    }
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(yaml.dump(compose_data))

    iso_path = tmp_path / "win2022.iso"
    iso_path.write_bytes(b"fake iso content")

    ChallengeManager._inject_windows_iso(compose_path, str(iso_path))

    result = yaml.safe_load(compose_path.read_text())
    assert result["services"]["web"]["volumes"] == ["/data:/usr/share/nginx/html"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -m pytest tests/test_iso_injection.py::test_inject_iso_mount_into_compose -x -v`
Expected: FAIL with `AttributeError: type object 'ChallengeManager' has no attribute '_inject_windows_iso'`

- [ ] **Step 3: Implement the injection helper**

In `benchmark_platform/utils/challenge.py`, add another static method to ChallengeManager:

```python
@staticmethod
def _inject_windows_iso(compose_path: Path, iso_path: str) -> None:
    """Append ISO bind mount to dockur services in the compose file."""
    with open(compose_path) as f:
        data = yaml.safe_load(f)

    for svc in data.get("services", {}).values():
        image = svc.get("image", "")
        if "dockur" in image.lower():
            volumes = svc.setdefault("volumes", [])
            mount = f"{iso_path}:/storage/custom.iso:ro"
            if mount not in volumes:
                volumes.append(mount)

    with open(compose_path, 'w') as f:
        yaml.dump(data, f)
```

- [ ] **Step 4: Wire injection into `start_challenge_instance`**

In `start_challenge_instance()`, after the block that handles `_create_challenge` / code alias (around line 511, before `self._compose(benchmark_id, challenge_code, 'up', '-d')`), add:

```python
if challenge.requires_windows_iso:
    from benchmark_platform.db import get_setting
    iso_path = get_setting("win2022_iso_path", "")
    if not iso_path:
        raise RuntimeError("请先在系统设置中配置 Windows Server 2022 ISO 路径")
    if not Path(iso_path).is_file():
        raise RuntimeError(f"Windows ISO 文件不存在: {iso_path}")
    compose_path = Challenge.get_base_path(benchmark_id, challenge_code, self.runtime_dir) / "docker-compose.yml"
    self._inject_windows_iso(compose_path, iso_path)
```

- [ ] **Step 5: Run all tests**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add benchmark_platform/utils/challenge.py tests/test_iso_injection.py
git commit -m "feat: inject Windows ISO bind mount into dockur services at start"
```

---

### Task 4: Settings API routes

**Files:**
- Modify: `benchmark_platform/server.py` (add routes after the runtime_dir block, around line 701)

- [ ] **Step 1: Add GET and POST routes**

In `benchmark_platform/server.py`, after the `set_runtime_dir_api` function (around line 701), add:

```python
@app.get("/api/settings/win_iso")
async def get_win_iso_api():
    return _ok({"win2022_iso_path": get_setting("win2022_iso_path", "")})


class WinIsoRequest(PydanticBaseModel):
    path: str


@app.post("/api/settings/win_iso")
async def set_win_iso_api(payload: WinIsoRequest):
    path = payload.path.strip()
    if not path:
        _err("路径不能为空", 400)
        return
    if not os.path.isfile(path):
        _err(f"文件不存在: {path}", 400)
        return
    set_setting("win2022_iso_path", path)
    return _ok({"win2022_iso_path": path}, "已保存")
```

- [ ] **Step 2: Add `os` import if missing**

Check if `import os` is already at the top of `server.py`. If not, add it. (It likely is already there via `from pathlib import Path` usage, but verify.)

Run: `grep -n "^import os" benchmark_platform/server.py`

If not present, add `import os` near the top imports.

- [ ] **Step 3: Verify server starts without error**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -c "from benchmark_platform.server import app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add benchmark_platform/server.py
git commit -m "feat: add GET/POST /api/settings/win_iso routes"
```

---

### Task 5: Settings UI — Windows ISO card

**Files:**
- Modify: `benchmark_platform/web/templates/pages/settings.html`

- [ ] **Step 1: Add the HTML card**

In `settings.html`, before the closing `</div>` of the Alpine x-data container (before line 138), add a new card section:

```html
  <!-- Windows ISO Settings -->
  <div class="bg-white border border-gray-200 rounded-xl p-5 mb-5">
    <h3 class="text-[13px] font-semibold text-gray-800 mb-4">Windows ISO</h3>
    <p class="text-[11px] text-gray-500 mb-4">AD 域渗透靶场（dockur/windows）启动时需要此 ISO。请提供 Windows Server 2022 Evaluation ISO 的本地绝对路径。</p>

    <div class="space-y-4">
      <div>
        <label class="block text-[11px] font-medium text-gray-600 mb-1.5">ISO 文件路径</label>
        <div class="flex items-center gap-3">
          <input type="text" x-model="winIsoPath" placeholder="/path/to/win2022.iso"
                 class="flex-1 h-9 px-3 text-[12px] border border-gray-200 rounded-lg focus:outline-none focus:border-gray-400 font-mono">
        </div>
        <p class="text-[10px] text-gray-400 mt-1.5">ISO 下载地址：https://www.microsoft.com/en-us/evalcenter/evaluate-windows-server-2022</p>
      </div>

      <div class="flex items-center gap-3 pt-2">
        <button @click="saveWinIso()" :disabled="savingWinIso"
                class="h-9 px-5 bg-gray-900 text-white text-[12px] font-medium rounded-lg hover:bg-gray-800 transition-colors cursor-pointer disabled:opacity-50">
          <span x-show="!savingWinIso">保存</span>
          <span x-show="savingWinIso">保存中...</span>
        </button>
        <span x-show="savedWinIso" x-transition class="text-[11px] text-emerald-600 font-medium">已保存</span>
      </div>
    </div>
  </div>
```

- [ ] **Step 2: Add Alpine.js state and methods**

In the `settingsPage()` function's return object, add these properties after the `savedTimeout` property:

```javascript
    winIsoPath: '',
    savingWinIso: false,
    savedWinIso: false,
```

In the `init()` method, add a fetch for the ISO path:

```javascript
      fetch('/api/settings/win_iso')
        .then(r => r.json())
        .then(d => {
          this.winIsoPath = d.data.win2022_iso_path || '';
        });
```

Add the `saveWinIso` method after `saveTimeout()`:

```javascript
    saveWinIso() {
      this.savingWinIso = true;
      this.savedWinIso = false;
      fetch('/api/settings/win_iso', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: this.winIsoPath})
      })
      .then(r => r.json())
      .then(d => {
        this.savingWinIso = false;
        if (d.code === 0) {
          this.savedWinIso = true;
          this.$dispatch('toast', {type: 'success', message: 'Windows ISO 路径已保存'});
          setTimeout(() => this.savedWinIso = false, 3000);
        } else {
          this.$dispatch('toast', {type: 'error', message: d.detail?.message || d.message || '保存失败'});
        }
      });
    },
```

- [ ] **Step 3: Commit**

```bash
git add benchmark_platform/web/templates/pages/settings.html
git commit -m "feat: add Windows ISO path setting to Settings UI"
```

---

### Task 6: Frontend hint on challenge card

**Files:**
- Modify: `benchmark_platform/web/context.py:56-77` (`_challenge_to_card`)
- Modify: `benchmark_platform/web/templates/components/challenge_card.html`
- Modify: `tests/test_web_context.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web_context.py`:

```python
def test_challenge_to_card_requires_windows_iso():
    """Challenge with requires_windows_iso should pass it to card context."""
    c = Challenge(
        challenge_code="ad001",
        difficulty=Difficulty.MEDIUM,
        points=300,
        hint_viewed=False,
        solved=False,
        target_info=TargetInfo(ip="localhost", port=[8080]),
        requires_windows_iso=True,
    )
    c.set_benchmark_id("AD-001")

    mgr = _make_manager([c])

    with patch.object(Challenge, 'get_benchmark', _fake_get_benchmark):
        with patch('benchmark_platform.db.is_challenge_enabled', return_value=True):
            from benchmark_platform.web.context import _challenge_to_card
            card = _challenge_to_card(mgr, c)

    assert card["requires_windows_iso"] is True


def test_challenge_to_card_no_windows_iso():
    """Normal challenge should have requires_windows_iso=False."""
    c = _make_challenge("001", 1)
    mgr = _make_manager([c])

    with patch.object(Challenge, 'get_benchmark', _fake_get_benchmark):
        with patch('benchmark_platform.db.is_challenge_enabled', return_value=True):
            from benchmark_platform.web.context import _challenge_to_card
            card = _challenge_to_card(mgr, c)

    assert card["requires_windows_iso"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -m pytest tests/test_web_context.py::test_challenge_to_card_requires_windows_iso -x -v`
Expected: FAIL with `KeyError: 'requires_windows_iso'`

- [ ] **Step 3: Add field to `_challenge_to_card`**

In `benchmark_platform/web/context.py`, in the return dict of `_challenge_to_card()` (around line 76, after `"expires_at": expires_at,`), add:

```python
        "requires_windows_iso": challenge.requires_windows_iso,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -m pytest tests/test_web_context.py -x -v`
Expected: All pass

- [ ] **Step 5: Add amber hint to challenge card template**

In `benchmark_platform/web/templates/components/challenge_card.html`, after the description paragraph (line 52: `<p class="text-[12px] text-gray-500 line-clamp-2">{{ card.description }}</p>`), add:

```html
  <!-- Windows ISO timing hint -->
  {% if card.requires_windows_iso and not card.unsupported %}
  <p class="text-[11px] text-amber-600">⏱ 首次启动需安装 Windows，预计 15-30 分钟</p>
  {% endif %}
```

- [ ] **Step 6: Run all tests**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add benchmark_platform/web/context.py benchmark_platform/web/templates/components/challenge_card.html tests/test_web_context.py
git commit -m "feat: show Windows ISO timing hint on dockur challenge cards"
```

---

### Task 7: Manual integration test

**Files:** None (verification only)

- [ ] **Step 1: Start the platform**

```bash
cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform
python3 -m benchmark_platform.server --benchmark-folder ./challenges --port 8088 --public-accessible-host localhost
```

- [ ] **Step 2: Verify Settings page**

Open `http://localhost:8088/web/settings` — confirm the "Windows ISO" card renders with an input field.

- [ ] **Step 3: Test save without valid path**

Enter a non-existent path, click Save. Confirm error toast "文件不存在: ...".

- [ ] **Step 4: Test save with valid path (if ISO available)**

If you have a Windows ISO file, enter its path. Confirm success toast.

- [ ] **Step 5: Verify challenge card hint**

Open `http://localhost:8088/web/challenges` — on AD-001 (if present and not unsupported), confirm the amber "首次启动需安装 Windows，预计 15-30 分钟" text appears.

- [ ] **Step 6: Test start without ISO configured**

Clear the ISO path setting. Try to start an AD challenge via API:
```bash
curl -X POST http://localhost:8088/api/start_challenge -H "Content-Type: application/json" -d '{"code":"<AD_CHALLENGE_CODE>"}'
```
Expected: Error response mentioning "请先在系统设置中配置 Windows Server 2022 ISO 路径"

- [ ] **Step 7: Confirm non-AD challenges unaffected**

Start any non-AD challenge — it should start normally without any ISO check.
