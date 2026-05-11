"""Web UI page routes and HTMX partial routes."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from benchmark_platform.web.context import (
    _challenge_to_card,
    challenges_context,
    dashboard_context,
    history_context,
    status_context,
)

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=_templates_dir)

web_router = APIRouter()


def _get_manager(request: Request):
    return request.app.state.manager


def _get_store(request: Request):
    return request.app.state.submission_store


def _render(request: Request, template: str, ctx: dict):
    from benchmark_platform import __version__
    manager = _get_manager(request)
    ctx.setdefault("no_level_gate", manager.no_level_gate if manager else False)
    ctx.setdefault("version", __version__)
    return templates.TemplateResponse(request, template, context=ctx)


# -- Page routes ---------------------------------------------------------------

@web_router.get("/dashboard")
async def page_dashboard(request: Request):
    manager = _get_manager(request)
    store = _get_store(request)
    if manager and store:
        ctx = dashboard_context(manager, store)
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
    ctx = challenges_context(manager) if manager else {"level_groups": [], "total_challenges": 0, "total_flags": 0}
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
        ctx = status_context(manager)
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
    if manager and store:
        ctx = dashboard_context(manager, store)
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
async def partial_challenge_card(request: Request, code: str):
    manager = _get_manager(request)
    card = None
    if manager:
        try:
            challenge = manager._find_by_code(code)
            card = _challenge_to_card(manager, challenge)
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
        ctx = status_context(manager)
    else:
        ctx = {"running": [], "stopped": [], "running_count": 0, "stopped_count": 0, "total": 0}
    return _render(request, "partials/status_table.html", ctx)


@web_router.get("/partials/sidebar_summary")
async def partial_sidebar_summary(request: Request):
    manager = _get_manager(request)
    if manager:
        running_count = sum(
            1 for c in manager.challenges
            if manager.get_instance_status(c.challenge_code) == "running"
        )
        ctx = {
            "running_count": running_count,
            "total_challenges": len(manager.challenges),
            "solved_flags": sum(c.solved_count for c in manager.challenges),
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
