# Repo Split & Challenge Distribution Design

## Goal

Split benchmark-platform into two repos — platform engine and challenge data — with a built-in download mechanism so users can fetch challenges directly from the Web UI.

## Architecture

```
wgpsec/benchmark-platform (platform engine)
    ├── Web UI "靶场管理" page
    ├── Downloads manifest.json from GitHub Release
    ├── Downloads individual challenge zips on demand
    └── Extracts to challenges/{category}/{name}/

wgpsec/ctf-benchmarks (challenge data)
    ├── xbow/XBEN-001-24/
    ├── xbow/XBEN-002-24/
    ├── custom/XBOW-XSS-A/
    ├── .github/workflows/pack-challenges.yml
    └── Published as GitHub Release assets
```

## ctf-benchmarks Repo

### Directory Structure

```
ctf-benchmarks/
├── xbow/
│   ├── XBEN-001-24/
│   │   ├── docker-compose.yml
│   │   ├── benchmark.json
│   │   ├── .env
│   │   └── app/
│   ├── XBEN-002-24/
│   └── ...
├── custom/
│   ├── XBOW-XSS-A/
│   ├── XBOW-XSS-B/
│   ├── XBOW-XSS-C/
│   └── XBOW-AUTH/
├── .github/workflows/pack-challenges.yml
├── .gitignore
└── README.md
```

### GitHub Action: Incremental Pack & Publish

**Trigger:** Push to main branch.

**Logic:**

1. Detect changed challenge directories using `git diff --name-only HEAD~1 HEAD` (or compare against the previous successful run commit)
2. For each changed challenge directory, create a zip: `{category}--{name}.zip` (e.g., `xbow--XBEN-001-24.zip`)
3. Generate/update `manifest.json` (always regenerated from full directory scan, not incremental)
4. Upload changed zips + updated manifest.json to a fixed Release (tag: `latest`)
   - Use `gh release upload --clobber` to overwrite existing assets for updated challenges
   - Unchanged challenge zips are left as-is (not re-uploaded)

**manifest.json schema:**

```json
{
  "version": "2026-05-11T12:00:00Z",
  "repo": "wgpsec/ctf-benchmarks",
  "challenges": [
    {
      "name": "XBEN-001-24",
      "category": "xbow",
      "asset": "xbow--XBEN-001-24.zip",
      "description": "SSH Command Injection",
      "difficulty": "easy"
    }
  ]
}
```

The `description` and `difficulty` fields are extracted from each challenge's `benchmark.json` during the Action run.

### Change Detection Logic

```bash
# Get list of changed files
CHANGED=$(git diff --name-only HEAD~1 HEAD)

# Extract unique challenge directories that changed
# e.g., "xbow/XBEN-001-24/app/server.py" -> "xbow/XBEN-001-24"
CHALLENGES_TO_PACK=$(echo "$CHANGED" | grep -E '^(xbow|custom)/' | cut -d'/' -f1,2 | sort -u)
```

Only directories in `CHALLENGES_TO_PACK` get re-zipped and re-uploaded. If no challenge directories changed (e.g., only README or workflow edits), skip packing entirely.

## benchmark-platform (Platform Side)

### Web UI: Challenge Store Page

A new page under "系统" nav group: "靶场管理" (Challenge Store).

**Functionality:**

1. **Fetch manifest** — On page load, fetch `manifest.json` from GitHub Release API (`https://github.com/wgpsec/ctf-benchmarks/releases/download/latest/manifest.json`)
2. **Display list** — Show all available challenges in a table grouped by category, with columns: name, description, difficulty, status (downloaded / not downloaded)
3. **Download all** — Button to download and extract all challenges
4. **Download single** — Per-challenge download button
5. **Status detection** — Check if `challenges/{category}/{name}/docker-compose.yml` exists to determine "downloaded" state

### Download Flow

1. Platform downloads the zip from GitHub Release URL
2. Extracts to `challenges/{category}/{name}/`
3. Returns success/failure to frontend
4. Frontend updates the status badge

### API Endpoints

| Route | Method | Description |
|-------|--------|-------------|
| `GET /api/store/manifest` | GET | Fetch and return manifest (cached with TTL) |
| `POST /api/store/download` | POST | Download a single challenge `{category, name}` |
| `POST /api/store/download-all` | POST | Download all challenges |

### Configuration

The GitHub Release URL is hardcoded (source repo: `wgpsec/ctf-benchmarks`, tag: `latest`). No configuration needed from user.

### Platform README Update

Replace current "Prepare Challenge Data" section with:

```markdown
### Prepare Challenge Data

Start the platform and navigate to "靶场管理" (Challenge Store) in the Web UI to download challenges. Alternatively, download manually:

\`\`\`bash
git clone https://github.com/wgpsec/ctf-benchmarks /tmp/benchmarks
cp -r /tmp/benchmarks/xbow challenges/xbow
cp -r /tmp/benchmarks/custom challenges/custom
rm -rf /tmp/benchmarks
\`\`\`
```

## Platform Side Changes Summary

- New page: `templates/pages/store.html`
- New API routes in `server.py` or `web/routes.py`: manifest fetch, download single, download all
- Sidebar nav: add "靶场管理" item
- No changes to existing challenge loading logic (`--benchmark-folder` remains as-is)
- User starts with: `--benchmark-folder ./challenges/xbow --benchmark-folder ./challenges/custom`

## Out of Scope

- Authentication for private repos (public repo only)
- Challenge deletion/cleanup from Web UI
- Version pinning or rollback (always pulls latest)
- CLI-based download command
