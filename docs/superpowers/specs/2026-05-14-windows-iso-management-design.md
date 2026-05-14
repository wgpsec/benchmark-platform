# Windows ISO Management Design

## Goal

Allow the platform to automatically inject a local Windows Server 2022 ISO into dockur/windows-based challenges (AD series), eliminating the need for runtime ISO downloads and providing clear user guidance on first-start timing.

## Background

AD challenges use `dockurr/windows` Docker images that require a Windows Server 2022 installation ISO. Without pre-staging the ISO, the container attempts to download ~5GB from Microsoft CDN on first start — which fails in air-gapped environments and is slow everywhere else. The `dockur/windows` container accepts a pre-staged ISO at `/storage/custom.iso`.

## Architecture

The feature has three independent components that integrate with existing platform patterns:

1. **Settings persistence** — a new `win2022_iso_path` key in the existing SQLite settings table
2. **Startup injection** — dynamic docker-compose.yml modification (same pattern as port remapping)
3. **Frontend hint** — a static notice on challenge cards that require Windows ISO

## Detailed Design

### 1. Settings: `win2022_iso_path`

**Storage:** `set_setting("win2022_iso_path", value)` / `get_setting("win2022_iso_path")`

**API routes:**

- `GET /api/settings/win_iso` → `{"code": 0, "data": {"win2022_iso_path": "..."} }`
- `POST /api/settings/win_iso` with body `{"path": "/absolute/path/to/win2022.iso"}`
  - Validates: path is non-empty, `os.path.isfile(path)` returns True
  - On validation failure: returns `{"code": -1, "message": "文件不存在: ..."}`
  - On success: persists and returns `{"code": 0, "message": "已保存"}`

**Frontend:** New card in `settings.html` titled "Windows ISO"：
- Text input for absolute path
- Save button with validation feedback
- Helper text: "AD 域渗透靶场（dockur/windows）启动时需要此 ISO。请提供 Windows Server 2022 Evaluation ISO 的本地路径。"

**Behavior:** Setting takes effect immediately (read at challenge start time, no restart needed).

### 2. Challenge Model: `requires_windows_iso`

**Field:** `requires_windows_iso: bool = False` on the `Challenge` dataclass.

**Detection:** During `_create_challenge()` and `_restore_challenge()`, after parsing `docker-compose.yml`, scan all services for an `image` field containing the substring `dockur` (case-insensitive). If found, set `requires_windows_iso = True`.

### 3. Startup Injection

**Location:** In `start_challenge_instance()`, after `_create_challenge()` returns and before `_compose(..., 'up', '-d')`.

**Logic (only when `challenge.requires_windows_iso` is True):**

1. Read `get_setting("win2022_iso_path")`
2. If empty → raise `RuntimeError("请先在系统设置中配置 Windows Server 2022 ISO 路径")`
3. If path does not exist on disk → raise `RuntimeError(f"Windows ISO 文件不存在: {path}")`
4. Open the runtime copy's `docker-compose.yml`
5. For each service whose `image` contains `dockur`:
   - Append `f"{iso_path}:/storage/custom.iso:ro"` to its `volumes` list
6. Write back the modified YAML

**Error handling:** RuntimeError is caught by the existing exception handler in `tch_start_challenge` (API) and `start_challenge` (MCP), returning appropriate error messages to the caller.

### 4. Frontend Hint

**Context:** In `_challenge_to_card()` (web/context.py), add `"requires_windows_iso": challenge.requires_windows_iso` to the returned dict.

**Template:** In `challenge_card.html`, when `card.requires_windows_iso` is True and `card.unsupported` is False (i.e., the challenge CAN run on this platform):
- Show an amber text line: "⏱ 首次启动需安装 Windows，预计 15-30 分钟"
- Position: below the description, above the action buttons

### 5. Non-goals / Exclusions

- No ISO download automation (user provides the file)
- No ISO integrity verification beyond file existence
- No support for other Windows versions (only Server 2022 for now)
- No changes to API/MCP response schemas (the hint is frontend-only)
- No changes to prebuild flow (prebuild only builds images, not related to ISO)
- No volume lifecycle changes (existing `docker compose down` without `-v` preserves installed state)

## Impact Analysis

| Area | Impact |
|------|--------|
| Non-dockur challenges | Zero — injection only triggers on `requires_windows_iso == True` |
| API/MCP contract | Zero — no new fields in TCH-facing responses |
| Existing settings | Zero — new key only, no schema changes |
| Docker Compose modification | Same pattern as port remapping (already battle-tested) |
| First start performance | With ISO: ~15-30 min Windows install. Without ISO config: blocked with clear error |
| Subsequent starts | Instant (volume preserves installed Windows) |

## Requirements

- Docker >= 23.0 (file-level bind mount over named volume)
- Host has read access to the ISO file path
- ISO must be Windows Server 2022 Evaluation (~5GB)
