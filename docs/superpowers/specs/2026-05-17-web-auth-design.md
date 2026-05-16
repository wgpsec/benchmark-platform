# Web UI Authentication Design

## Problem

Platform has no authentication on the Web UI. When deployed to a public network, anyone can access admin functionality (start/stop challenges, view all data, modify settings).

## Roles

| Role | Token | Access |
|------|-------|--------|
| Admin | Default team's Agent-Token | Full Web UI access (all pages) |
| Observer | Any other team's Agent-Token | Read-only scoreboard page only |

API endpoints (`/api/*`) retain the existing `Agent-Token` header mechanism unchanged.

## Auth Flow

1. User visits any `/web/*` page
2. Middleware checks for signed `session` cookie
3. If missing/invalid → redirect to `/web/login`
4. Login page: user enters their Agent-Token
5. Backend validates token against teams table:
   - Matches default team → role = admin
   - Matches other team → role = observer
   - No match → error "Invalid token"
6. On success: set signed cookie (7-day expiry), redirect to appropriate homepage
7. Subsequent requests: middleware parses cookie, injects `request.state.user`
8. Route access control:
   - Admin → all `/web/*` pages
   - Observer → only `/web/scoreboard`, other paths redirect to scoreboard

## Whitelisted Paths (no auth required)

- `/web/login` (GET + POST)
- `/api/*` (uses Agent-Token header, unchanged)
- `/mcp` (MCP server)
- Static assets

## Cookie Structure

Payload signed with `itsdangerous.URLSafeTimedSerializer`:

```json
{"team_id": "uuid", "role": "admin|observer", "team_name": "Team Name"}
```

Cookie attributes: `httponly=True`, `samesite=Lax`, `max_age=604800` (7 days).

## SECRET_KEY

- Read from `SECRET_KEY` environment variable
- If not configured: generate random value at startup + log warning (all sessions invalidate on restart)
- Admin can reset SECRET_KEY via Settings page to force-logout all sessions

## Components

### New Files

- `benchmark_platform/web/auth_middleware.py` — Starlette middleware for cookie validation + route access control; helper functions for cookie signing/verification

### Modified Files

- `benchmark_platform/server.py` — Register auth middleware
- `benchmark_platform/web/routes.py` — Add `/web/login` (GET/POST), `/web/logout`, `/web/scoreboard`
- `benchmark_platform/web/templates/pages/login.html` — Login page template
- `benchmark_platform/web/templates/pages/scoreboard.html` — Observer dashboard
- `benchmark_platform/web/templates/components/sidebar.html` — Hide menu items for observer role (defensive, since observer can't reach those pages anyway)

### New Dependency

- `itsdangerous` — Signed cookie serialization with timestamp-based expiry

## Observer Scoreboard Page

- Standalone full-screen layout (no admin sidebar)
- Header: platform name + logged-in team name + logout button
- Body: all teams' challenge progress
  - Team name
  - Per-challenge completion (flags done / total)
  - Overall completion rate
- Auto-refresh via HTMX polling (30-second interval)
- No action buttons, no management links, no settings

## Security

- Cookies: `httponly`, `samesite=Lax`
- HTTPS expected via reverse proxy (platform does not enforce)
- No CSRF protection (internal tool, admin-only operations)
- No brute-force protection (tokens are UUIDs, high entropy)
- Token change does not immediately invalidate existing sessions (stateless tradeoff, 7-day max window; SECRET_KEY reset available for immediate invalidation)

## Not In Scope

- User management CRUD (no creating/editing users)
- Password-based login (token-only)
- Multi-session tracking
- Rate limiting
