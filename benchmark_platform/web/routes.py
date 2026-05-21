"""Web UI page routes and HTMX partial routes."""
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse

from benchmark_platform.web.auth_middleware import create_session_cookie, _COOKIE_NAME
from benchmark_platform.web.context import (
    _challenge_to_card,
    challenges_context,
    dashboard_context,
    history_context,
    status_context,
)
from benchmark_platform.db import get_team_by_token, get_or_create_default_team, get_setting
from benchmark_platform.web.ui_visibility import get_ui_visibility

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=_templates_dir)

web_router = APIRouter()


def _get_manager(request: Request):
    return request.app.state.manager


def _get_store(request: Request):
    return request.app.state.submission_store


def _get_selected_team_id(request: Request) -> Optional[str]:
    """Read selected team from cookie. Falls back to default team."""
    team_id = request.cookies.get("selected_team_id")
    if not team_id:
        from benchmark_platform.db import get_or_create_default_team
        default_team = get_or_create_default_team()
        team_id = default_team["id"]
    return team_id


def _get_teams_for_selector(selected_team_id: Optional[str]) -> dict:
    """Get teams list and current selection for the topbar selector."""
    from benchmark_platform.db import list_teams, get_or_create_default_team
    teams = list_teams()
    if not selected_team_id and teams:
        default_team = get_or_create_default_team()
        selected_team_id = default_team["id"]
    return {"teams": teams, "selected_team_id": selected_team_id}


def _render(request: Request, template: str, ctx: dict):
    from benchmark_platform import __version__
    manager = _get_manager(request)
    ctx.setdefault("no_level_gate", manager.no_level_gate if manager else False)
    ctx.setdefault("version", __version__)
    ctx.setdefault("user", getattr(request.state, "user", {}))
    for key, value in get_ui_visibility().items():
        ctx.setdefault(key, value)
    team_selector = _get_teams_for_selector(_get_selected_team_id(request))
    ctx.setdefault("teams", team_selector["teams"])
    ctx.setdefault("selected_team_id", team_selector["selected_team_id"])
    return templates.TemplateResponse(request, template, context=ctx)


def _status_context_with_teams(manager) -> dict:
    """Build status context using DB instances with team information."""
    from benchmark_platform.db import get_all_instances, list_teams

    all_instances = get_all_instances()
    teams = {t["id"]: t["name"] for t in list_teams()}

    running = []
    stopped_challenges = []

    for record in all_instances:
        bm_id = record["benchmark_id"]
        team_name = teams.get(record["team_id"], "shared") if record["team_id"] else " (共享)"
        challenge = None
        for c in manager.challenges:
            if c.get_benchmark_id() == bm_id:
                challenge = c
                break
        if not challenge:
            continue

        bm = challenge.get_benchmark()
        ports = json.loads(record["ports"]) if record["ports"] else []
        entrypoint = [f"{manager.public_accessible_host}:{p}" for p in ports]

        card = {
            "name": bm.name,
            "benchmark_id": bm_id,
            "challenge_code": record["challenge_code"],
            "team_name": team_name,
            "team_id": record["team_id"],
            "entrypoint": entrypoint,
            "status": record["status"],
        }

        if record["status"] in ("running", "starting"):
            running.append(card)
        else:
            stopped_challenges.append(card)

    # Add challenges with no instances at all
    instanced_bids = {r["benchmark_id"] for r in all_instances}
    for c in manager.challenges:
        bm_id = c.get_benchmark_id()
        if bm_id not in instanced_bids:
            bm = c.get_benchmark()
            stopped_challenges.append({
                "name": bm.name,
                "benchmark_id": bm_id,
                "challenge_code": bm_id,
                "team_name": "—",
                "team_id": None,
                "entrypoint": [],
                "status": "stopped",
            })

    return {
        "running": running,
        "stopped": stopped_challenges,
        "running_count": len(running),
        "stopped_count": len(stopped_challenges),
        "total": len(running) + len(stopped_challenges),
    }


# -- Auth routes ---------------------------------------------------------------

@web_router.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request, "pages/login.html", context={"error": None})


@web_router.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    token = form.get("token", "").strip()

    if not token:
        return templates.TemplateResponse(
            request, "pages/login.html", context={"error": "Please enter a token"}
        )

    team = get_team_by_token(token)
    if team is None:
        return templates.TemplateResponse(
            request, "pages/login.html", context={"error": "Invalid token"}
        )

    default_team = get_or_create_default_team()
    role = "admin" if team["id"] == default_team["id"] else "observer"
    cookie_value = create_session_cookie(team["id"], role, team["name"])

    redirect_url = "/web/dashboard" if role == "admin" else "/web/scoreboard"
    response = RedirectResponse(redirect_url, status_code=302)
    response.set_cookie(
        _COOKIE_NAME,
        cookie_value,
        max_age=7 * 24 * 3600,
        httponly=True,
        samesite="lax",
    )
    return response


@web_router.get("/logout")
async def logout(request: Request):
    response = RedirectResponse("/web/login", status_code=302)
    response.delete_cookie(_COOKIE_NAME)
    return response


@web_router.get("/scoreboard")
async def scoreboard_page(request: Request):
    from benchmark_platform.db import list_teams
    teams_data = list_teams()
    teams_data.sort(key=lambda t: t.get("solved_flags", 0), reverse=True)
    manager = _get_manager(request)
    total_flags = sum(max(1, len(c.flag_states)) for c in manager.challenges) if manager else 1
    user = getattr(request.state, "user", {})
    return templates.TemplateResponse(
        request,
        "pages/scoreboard.html",
        context={
            "teams": teams_data,
            "total_flags": total_flags or 1,
            "user": user,
            "page": "scoreboard",
        },
    )


# -- Page routes ---------------------------------------------------------------

@web_router.get("/dashboard")
async def page_dashboard(request: Request):
    manager = _get_manager(request)
    store = _get_store(request)
    team_id = _get_selected_team_id(request)
    if manager and store:
        ctx = dashboard_context(manager, store, team_id=team_id)
    else:
        ctx = {
            "total_challenges": 0, "solved_challenges": 0,
            "total_flags": 0, "solved_flags": 0,
            "total_points": 0, "earned_points": 0,
            "running_count": 0, "level_progress": [],
            "difficulty_stats": [], "recent_submissions": [],
            "submission_total": 0, "submission_correct": 0, "submission_incorrect": 0,
        }
    return _render(request, "pages/dashboard.html", {"page": "dashboard", **ctx})


@web_router.get("/challenges")
async def page_challenges(request: Request):
    manager = _get_manager(request)
    team_id = _get_selected_team_id(request)
    ctx = challenges_context(manager, team_id=team_id) if manager else {"level_groups": [], "total_challenges": 0, "total_flags": 0}
    return _render(request, "pages/challenges.html", {"page": "challenges", **ctx})


@web_router.get("/history")
async def page_history(request: Request):
    store = _get_store(request)
    if store:
        ctx = history_context(store)
    else:
        ctx = {"records": [], "total": 0, "correct_count": 0, "incorrect_count": 0, "filter_correct": None, "limit": 50, "offset": 0}
    return _render(request, "pages/history.html", {"page": "history", **ctx})


@web_router.get("/status")
async def page_status(request: Request):
    manager = _get_manager(request)
    if manager:
        ctx = _status_context_with_teams(manager)
    else:
        ctx = {"running": [], "stopped": [], "running_count": 0, "stopped_count": 0, "total": 0}
    return _render(request, "pages/status.html", {"page": "status", **ctx})


@web_router.get("/store")
async def page_store(request: Request):
    return _render(request, "pages/store.html", {"page": "store"})


@web_router.get("/prebuild")
async def page_prebuild(request: Request):
    manager = _get_manager(request)
    prebuild_mgr = getattr(request.app.state, "prebuild_manager", None)

    if manager and prebuild_mgr is None:
        from benchmark_platform.web.prebuild_manager import PrebuildManager
        prebuild_mgr = PrebuildManager(manager.challenges, manager.benchmark_folders)
        prebuild_mgr.check_cached()
        request.app.state.prebuild_manager = prebuild_mgr

    cached_count = prebuild_mgr.cached_count if prebuild_mgr else 0
    total_count = prebuild_mgr.total_count if prebuild_mgr else 0

    return _render(request, "pages/prebuild.html", {
        "page": "prebuild",
        "cached_count": cached_count,
        "total_count": total_count,
    })


# -- Partial routes (HTMX) ---------------------------------------------------

@web_router.get("/partials/dashboard_stats")
async def partial_dashboard_stats(request: Request):
    manager = _get_manager(request)
    store = _get_store(request)
    team_id = _get_selected_team_id(request)
    if manager and store:
        ctx = dashboard_context(manager, store, team_id=team_id)
    else:
        ctx = {
            "total_challenges": 0, "solved_challenges": 0,
            "total_flags": 0, "solved_flags": 0,
            "total_points": 0, "earned_points": 0,
            "running_count": 0, "level_progress": [],
            "difficulty_stats": [], "recent_submissions": [],
            "submission_total": 0, "submission_correct": 0, "submission_incorrect": 0,
        }
    return _render(request, "partials/dashboard_stats.html", ctx)


@web_router.get("/partials/challenge_card")
async def partial_challenge_card(request: Request, code: str = "", benchmark_id: str = ""):
    manager = _get_manager(request)
    team_id = _get_selected_team_id(request)
    card = None
    if manager:
        try:
            if benchmark_id:
                challenge = next(
                    (c for c in manager.challenges if c.get_benchmark_id() == benchmark_id),
                    None,
                )
                if challenge is None:
                    raise KeyError(benchmark_id)
            else:
                challenge = manager._find_by_code(code)
            card = _challenge_to_card(manager, challenge, team_id=team_id)
        except KeyError:
            pass
    return _render(request, "partials/challenge_card_single.html", {"card": card})


@web_router.get("/partials/history_rows")
async def partial_history_rows(request: Request):
    store = _get_store(request)
    if store:
        ctx = history_context(store)
    else:
        ctx = {"records": [], "total": 0, "correct_count": 0, "incorrect_count": 0}
    return _render(request, "partials/history_rows.html", ctx)


@web_router.get("/partials/status_table")
async def partial_status_table(request: Request):
    manager = _get_manager(request)
    if manager:
        ctx = _status_context_with_teams(manager)
    else:
        ctx = {"running": [], "stopped": [], "running_count": 0, "stopped_count": 0, "total": 0}
    return _render(request, "partials/status_table.html", ctx)


@web_router.get("/partials/sidebar_summary")
async def partial_sidebar_summary(request: Request):
    manager = _get_manager(request)
    team_id = _get_selected_team_id(request)
    if manager:
        running_count = sum(
            1 for c in manager.challenges
            if manager.get_instance_status(c.challenge_code) == "running"
        )
        if team_id:
            from benchmark_platform.db import get_team_solved_count
            solved_flags = sum(
                get_team_solved_count(team_id, c.get_benchmark_id())
                for c in manager.challenges
            )
        else:
            solved_flags = sum(c.solved_count for c in manager.challenges)
        ctx = {
            "running_count": running_count,
            "total_challenges": len(manager.challenges),
            "solved_flags": solved_flags,
            "total_flags": sum(c.flag_count for c in manager.challenges),
        }
    else:
        ctx = {}
    return _render(request, "components/_sidebar_summary_content.html", ctx)


# -- Team management routes ----------------------------------------------------

@web_router.get("/teams")
async def page_teams(request: Request):
    from benchmark_platform.db import list_teams
    teams = list_teams()
    return _render(request, "pages/teams.html", {"page": "teams", "teams": teams})


@web_router.get("/settings")
async def page_settings(request: Request):
    return _render(request, "pages/settings.html", {
        "page": "settings",
        "max_instances_per_team": int(get_setting("max_instances_per_team", "3")),
    })


@web_router.post("/api/teams/create")
async def api_create_team(request: Request):
    from benchmark_platform.db import create_team
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        return {"code": -1, "message": "队伍名称不能为空", "data": None}
    try:
        team = create_team(name)
    except ValueError as e:
        return {"code": -1, "message": str(e), "data": None}
    return {"code": 0, "message": "创建成功", "data": team}


@web_router.get("/api/teams")
async def api_list_teams(request: Request):
    from benchmark_platform.db import list_teams
    teams = list_teams()
    return {"code": 0, "message": "success", "data": teams}


@web_router.post("/api/teams/reset")
async def api_reset_team(request: Request):
    from benchmark_platform.db import reset_team_progress
    body = await request.json()
    team_id = body.get("team_id", "").strip()
    if not team_id:
        return {"code": -1, "message": "缺少 team_id", "data": None}
    reset_team_progress(team_id)
    return {"code": 0, "message": "进度已重置", "data": None}


@web_router.post("/api/teams/switch")
async def api_switch_team(request: Request):
    body = await request.json()
    team_id = body.get("team_id", "").strip()
    if not team_id:
        return JSONResponse({"code": -1, "message": "缺少 team_id", "data": None})
    response = JSONResponse({"code": 0, "message": "切换成功", "data": {"team_id": team_id}})
    response.set_cookie("selected_team_id", team_id, max_age=86400 * 365, httponly=False, samesite="lax")
    return response
