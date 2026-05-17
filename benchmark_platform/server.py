from __future__ import annotations

import asyncio
import atexit
import os
import secrets
import signal
import threading
from pathlib import Path
from typing import NoReturn

import typer
import uvicorn
from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi import HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel as PydanticBaseModel

from benchmark_platform.base import Challenge
from benchmark_platform.base import CompetitionStage
from benchmark_platform.base import GetChallengeHintResponse
from benchmark_platform.base import GetChallengesResponse
from benchmark_platform.base import SubmitAnswerRequest
from benchmark_platform.base import SubmitAnswerResponse
from benchmark_platform.utils.challenge import ChallengeManager
from benchmark_platform.utils.logger import get_logger
from benchmark_platform.web.routes import web_router
from benchmark_platform.web.auth_middleware import AuthMiddleware
from benchmark_platform.web.submission_store import SubmissionStore
from benchmark_platform.auth import get_current_team, require_admin
from benchmark_platform.db import (
    init_db, get_or_create_default_team,
    mark_flag_solved, get_team_solved_count,
    is_hint_viewed, mark_hint_viewed, get_team_progress,
    get_level_gate_config, set_level_gate_config,
    get_setting, set_setting,
    is_challenge_enabled, set_challenge_enabled,
    set_challenges_enabled_bulk, get_challenge_visibility,
    get_instance_timeout_config, set_instance_timeout_config,
)


# Mount MCP server at /mcp
from contextlib import asynccontextmanager
from benchmark_platform.mcp_server import mcp

_mcp_app = mcp.http_app(path="/", transport="streamable-http")

@asynccontextmanager
async def lifespan(app):
    async with _mcp_app.lifespan(app):
        yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(AuthMiddleware)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(web_router, prefix="/web")
app.mount("/mcp", _mcp_app)

from benchmark_platform.web.vnc_proxy import router as vnc_router
app.include_router(vnc_router)


@app.exception_handler(HTTPException)
async def _tch_http_exception_handler(request: Request, exc: HTTPException):
    """Return TCH-compatible error format: top-level {code, message, data}."""
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        body = exc.detail
    else:
        body = {"code": -1, "message": str(exc.detail), "data": None}
    return JSONResponse(status_code=exc.status_code, content=body)


# ── tch Response helpers ──────────────────────────────────────────────────────

def _ok(data=None, message: str = "success") -> dict:
    return {"code": 0, "message": message, "data": data}


def _err(message: str, status_code: int = 400) -> NoReturn:
    raise HTTPException(
        status_code=status_code,
        detail={"code": -1, "message": message, "data": None},
    )


CHALLENGES: list[Challenge] = []
manager: ChallengeManager | None = None
logger = get_logger(Path('logs/competition-platform-server-logs.jsonl'))


def cleanup() -> None:
    """Cleanup wrapper"""
    if manager is not None:
        manager.stop()


def signal_handler(signum, _frame) -> None:
    """Handle exit signals"""
    logger.info('received exit signal', action='shutdown', signal=signum)
    cleanup()
    exit(0)


atexit.register(cleanup)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def _auto_reload_challenges() -> tuple[int, list[str]]:
    """Reload newly downloaded challenges into the running manager."""
    global CHALLENGES
    if manager is None:
        return 0, []
    added, errors = manager.reload()
    if added:
        CHALLENGES = manager.challenges
        # Invalidate prebuild manager so it picks up new challenges
        if hasattr(app.state, "prebuild_manager"):
            app.state.prebuild_manager = None
    return added, errors


@app.post("/api/challenges/reload")
async def reload_challenges(_=Depends(require_admin)):
    if manager is None:
        raise HTTPException(status_code=503, detail="Server not initialized")
    added, errors = _auto_reload_challenges()
    return _ok({
        "added": added,
        "errors": errors,
        "total": len(manager.challenges),
    }, f"加载了 {added} 个新靶场" if added else "没有发现新靶场")


@app.get('/api/v1/challenges', response_model=GetChallengesResponse)
async def get_challenges() -> GetChallengesResponse:
    logger.info(
        'get challenges request', action='api',
        endpoint='/api/v1/challenges', challenge_count=len(CHALLENGES),
    )
    return GetChallengesResponse(current_stage=CompetitionStage.COMPETITION, challenges=CHALLENGES)


@app.get('/api/v1/hint/{challenge_code}', response_model=GetChallengeHintResponse)
async def get_challenge_hint(challenge_code: str) -> GetChallengeHintResponse:
    challenge = next(
        (c for c in CHALLENGES if c.challenge_code == challenge_code), None,
    )
    if challenge is None:
        logger.warning(
            'challenge not found', action='api',
            endpoint='/api/v1/hint', challenge_code=challenge_code,
        )
        raise HTTPException(
            status_code=404, detail=f'Challenge {challenge_code} not found',
        )
    first_use = not challenge.hint_viewed
    challenge.hint_viewed = True
    try:
        hint_content = challenge.get_hint()
    except Exception as e:
        logger.error(
            'failed to get hint', action='api', endpoint='/api/v1/hint',
            challenge_code=challenge_code, error=str(e),
        )
        raise
    logger.info(
        'challenge hint retrieved', action='api', endpoint='/api/v1/hint',
        challenge_code=challenge_code, first_use=first_use,
    )
    return GetChallengeHintResponse(hint_content=hint_content, penalty_points=int(challenge.points * 0.1), first_use=first_use)


@app.post('/api/v1/answer', response_model=SubmitAnswerResponse)
async def submit_answer(payload: SubmitAnswerRequest) -> SubmitAnswerResponse:
    challenge = next(
        (c for c in CHALLENGES if c.challenge_code == payload.challenge_code), None,
    )
    if challenge is None:
        logger.warning(
            'challenge not found', action='api',
            endpoint='/api/v1/answer', challenge_code=payload.challenge_code,
        )
        raise HTTPException(
            status_code=404, detail=f'Challenge {payload.challenge_code} not found',
        )
    try:
        expected_answer = challenge.get_expected_answer()
    except Exception as e:
        logger.error(
            'failed to get expected answer', action='api',
            endpoint='/api/v1/answer', challenge_code=payload.challenge_code, error=str(e),
        )
        raise
    is_correct = expected_answer == payload.answer
    if is_correct:
        challenge.solved = True
    logger.info(
        'answer submitted', action='api', endpoint='/api/v1/answer', challenge_code=payload.challenge_code,
        correct=is_correct, earned_points=challenge.points if is_correct else 0,
    )
    return SubmitAnswerResponse(correct=is_correct, earned_points=challenge.points if is_correct else 0, is_solved=is_correct)


@app.get('/')
async def index():
    return RedirectResponse(url='/web/dashboard')


# ── tch-compatible API routes ─────────────────────────────────────────────────

def _ensure_challenge_enabled(challenge) -> None:
    """Agent-facing guard: 403 if admin has disabled this challenge for agents."""
    if not is_challenge_enabled(challenge.get_benchmark_id()):
        _err("该题目已被管理员关闭", 403)


@app.get("/api/challenges")
async def tch_get_challenges(team: dict = Depends(get_current_team)):
    if manager is None:
        _err("Server not initialized", 503)
        return  # unreachable, but makes control flow explicit

    all_challenges = [
        c for c in manager.challenges
        if is_challenge_enabled(c.get_benchmark_id())
    ]
    team_progress = get_team_progress(team["id"])
    challenge_list = []
    total_solved_challenges = 0
    for c in all_challenges:
        bm = c.get_benchmark()
        bm_id = c.get_benchmark_id()
        status = manager.get_instance_status(c.challenge_code)
        entrypoint = None
        if status in ("running", "unhealthy"):
            entrypoint = [f"{manager.public_accessible_host}:{p}" for p in c.target_info.port]

        team_solved = get_team_solved_count(team["id"], bm_id)
        all_solved = team_solved >= c.flag_count
        hint_viewed = is_hint_viewed(team["id"], bm_id)

        if all_solved:
            total_solved_challenges += 1

        if c.flag_count > 0:
            per_flag_score = c.points // c.flag_count
            got_score = per_flag_score * team_solved
        else:
            got_score = c.points if all_solved else 0

        # Per-flag solved status from DB
        progress_for_challenge = team_progress.get(bm_id, {})
        flags_info = None
        if c.flag_states:
            flags_info = [
                {"id": fs.id, "route": fs.route, "description": fs.description, "solved": progress_for_challenge.get(fs.id, False)}
                for fs in c.flag_states
            ]

        challenge_list.append({
            "benchmark_id": bm_id,
            "title": bm.name,
            "code": c.challenge_code,
            "difficulty": c.difficulty.value,
            "description": bm.description,
            "level": bm.level,
            "total_score": c.points,
            "total_got_score": got_score,
            "flag_count": c.flag_count,
            "flag_got_count": team_solved,
            "flags": flags_info,
            "hint_viewed": hint_viewed,
            "instance_status": status,
            "entrypoint": entrypoint,
            "unsupported": c.unsupported,
            "unsupported_reason": c.unsupported_reason,
        })

    return _ok({
        "current_level": manager.get_current_level(team["id"]),
        "total_challenges": len(all_challenges),
        "solved_challenges": total_solved_challenges,
        "challenges": challenge_list,
    })


class StartChallengeRequest(PydanticBaseModel):
    code: str


@app.post("/api/start_challenge")
async def tch_start_challenge(payload: StartChallengeRequest, team: dict = Depends(get_current_team)):
    if manager is None:
        _err("Server not initialized", 503)
        return  # unreachable, but makes control flow explicit

    try:
        challenge = manager._find_by_code(payload.code)
    except KeyError:
        _err(f"Challenge {payload.code} not found", 404)
        return  # unreachable, but makes control flow explicit

    _ensure_challenge_enabled(challenge)

    if challenge.unsupported:
        return _ok({"unsupported": True}, f"该赛题不支持当前平台: {challenge.unsupported_reason}")

    challenge_level = manager.get_level_for_challenge(challenge)
    if not manager.is_level_unlocked(challenge_level, team["id"]):
        _err(f"Level {challenge_level} 尚未解锁，请先通过前置关卡", 403)
        return

    team_solved = get_team_solved_count(team["id"], challenge.get_benchmark_id())
    if team_solved >= challenge.flag_count:
        return _ok({"already_completed": True}, "该赛题已全部完成，无需再启动实例")

    current_status = manager.get_instance_status(payload.code)
    if current_status in ("running", "unhealthy"):
        entrypoints = [f"{manager.public_accessible_host}:{p}" for p in challenge.target_info.port]
        return _ok(entrypoints, "赛题实例已在运行中")

    if current_status == "starting":
        return JSONResponse(
            status_code=202,
            content=_ok(None, "赛题正在启动中"),
        )

    try:
        result = await asyncio.to_thread(manager.start_challenge_instance, payload.code)
    except Exception as e:
        logger.error("start_challenge failed", action="api", challenge_code=payload.code, error=str(e))
        _err(f"赛题启动失败: {e}", 502)
        return  # unreachable, but makes control flow explicit

    if result is None:
        return JSONResponse(
            status_code=202,
            content=_ok(None, "赛题正在启动中，请通过日志面板查看进度"),
        )

    return _ok(result, "赛题实例启动成功")


class StopChallengeRequest(PydanticBaseModel):
    code: str


@app.post("/api/stop_challenge")
async def tch_stop_challenge(payload: StopChallengeRequest, team: dict = Depends(get_current_team)):
    if manager is None:
        _err("Server not initialized", 503)
        return  # unreachable, but makes control flow explicit

    try:
        challenge = manager._find_by_code(payload.code)
    except KeyError:
        _err(f"Challenge {payload.code} not found", 404)
        return  # unreachable, but makes control flow explicit

    _ensure_challenge_enabled(challenge)

    if manager.get_instance_status(payload.code) not in ("running", "unhealthy"):
        _err("赛题实例未运行", 400)
        return  # unreachable, but makes control flow explicit

    try:
        await asyncio.to_thread(manager.stop_challenge_instance, payload.code)
    except Exception as e:
        _err(f"停止失败: {e}", 502)
        return  # unreachable, but makes control flow explicit

    return _ok(None, "赛题实例已停止")


class SubmitFlagRequest(PydanticBaseModel):
    code: str
    flag: str


@app.post("/api/submit")
async def tch_submit(payload: SubmitFlagRequest, team: dict = Depends(get_current_team)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    try:
        challenge = manager._find_by_code(payload.code)
    except KeyError:
        _err(f"Challenge {payload.code} not found", 404)
        return

    _ensure_challenge_enabled(challenge)

    challenge_level = manager.get_level_for_challenge(challenge)
    if not manager.is_level_unlocked(challenge_level, team["id"]):
        _err(f"Level {challenge_level} 尚未解锁，请先通过前置关卡", 403)
        return

    if manager.get_instance_status(payload.code) not in ("running", "unhealthy"):
        _err("赛题实例未运行", 400)
        return

    try:
        answers = challenge.get_expected_answers()
    except Exception as e:
        _err(f"Failed to get expected answers: {e}", 500)
        return

    matched_flag_id = None
    for fid, fval in answers.items():
        if fval == payload.flag:
            matched_flag_id = fid
            break

    is_correct = matched_flag_id is not None

    if is_correct:
        mark_flag_solved(team["id"], challenge.get_benchmark_id(), matched_flag_id)
        for fs in challenge.flag_states:
            if fs.id == matched_flag_id:
                fs.solved = True
                break

    team_solved = get_team_solved_count(team["id"], challenge.get_benchmark_id())
    all_solved = team_solved >= challenge.flag_count
    if all_solved:
        challenge.solved = True

    # Record submission
    from datetime import datetime
    from benchmark_platform.web.submission_store import SubmissionRecord
    if hasattr(app.state, 'submission_store') and app.state.submission_store is not None:
        bm = challenge.get_benchmark()
        app.state.submission_store.add(SubmissionRecord(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            challenge_code=payload.code,
            benchmark_id=challenge.get_benchmark_id(),
            challenge_name=bm.name,
            flag_id=matched_flag_id,
            flag_value=payload.flag[:8] + "..." + payload.flag[-4:] if len(payload.flag) > 16 else payload.flag,
            correct=is_correct,
            points=challenge.points // challenge.flag_count if is_correct and challenge.flag_count > 0 else 0,
            team_id=team["id"],
            team_name=team["name"],
        ))

    if is_correct:
        per_flag_score = challenge.points // challenge.flag_count if challenge.flag_count > 0 else challenge.points
        msg = f"恭喜！答案正确（{team_solved}/{challenge.flag_count}），获得{per_flag_score}分"
    else:
        msg = "答案错误，请继续尝试"

    return _ok({
        "correct": is_correct,
        "flag_id": matched_flag_id,
        "message": msg,
        "flag_count": challenge.flag_count,
        "flag_got_count": team_solved,
        "all_solved": all_solved,
    })


class HintRequest(PydanticBaseModel):
    code: str


@app.get("/api/challenges/{code}/progress")
async def tch_get_progress(code: str, team: dict = Depends(get_current_team)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    try:
        challenge = manager._find_by_code(code)
    except KeyError:
        _err(f"Challenge {code} not found", 404)
        return

    _ensure_challenge_enabled(challenge)

    team_progress = get_team_progress(team["id"])
    bm_id = challenge.get_benchmark_id()
    progress_for_challenge = team_progress.get(bm_id, {})
    team_solved = get_team_solved_count(team["id"], bm_id)
    all_solved = team_solved >= challenge.flag_count

    if challenge.flag_states:
        flags_progress = [
            {"id": fs.id, "route": fs.route, "solved": progress_for_challenge.get(fs.id, False), "solved_at": None}
            for fs in challenge.flag_states
        ]
    else:
        flags_progress = [
            {"id": "default", "route": "/", "solved": all_solved, "solved_at": None}
        ]

    return _ok({
        "challenge_code": code,
        "flags": flags_progress,
        "solved_count": team_solved,
        "total_count": challenge.flag_count,
        "all_solved": all_solved,
    })


@app.post("/api/hint")
async def tch_hint(payload: HintRequest, team: dict = Depends(get_current_team)):
    if manager is None:
        _err("Server not initialized", 503)
        return  # unreachable, but makes control flow explicit

    try:
        challenge = manager._find_by_code(payload.code)
    except KeyError:
        _err(f"Challenge {payload.code} not found", 404)
        return  # unreachable, but makes control flow explicit

    _ensure_challenge_enabled(challenge)

    if manager.get_instance_status(payload.code) not in ("running", "unhealthy"):
        _err("请先启动赛题实例", 400)
        return  # unreachable, but makes control flow explicit

    try:
        hint = challenge.get_hint()
    except Exception as e:
        _err(f"Failed to get hint: {e}", 500)
        return  # unreachable, but makes control flow explicit

    mark_hint_viewed(team["id"], challenge.get_benchmark_id())
    return _ok({"code": payload.code, "hint_content": hint})


@app.post("/api/stop_all")
async def tch_stop_all(_=Depends(require_admin)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    stopped = []
    for c in manager.challenges:
        if manager.get_instance_status(c.challenge_code) in ("running", "unhealthy"):
            try:
                await asyncio.to_thread(manager.stop_challenge_instance, c.challenge_code)
                stopped.append(c.challenge_code)
            except Exception:
                pass
    return _ok({"stopped_count": len(stopped)}, f"已停止 {len(stopped)} 个实例")


async def _stop_instance_if_running(challenge_code: str) -> bool:
    if manager is None:
        return False
    if manager.get_instance_status(challenge_code) not in ("running", "unhealthy"):
        return False
    try:
        await asyncio.to_thread(manager.stop_challenge_instance, challenge_code)
        return True
    except Exception as e:
        logger.error("auto-stop on disable failed", challenge_code=challenge_code, error=str(e))
        return False


class ChallengeVisibilityRequest(PydanticBaseModel):
    code: str
    enabled: bool


@app.post("/api/challenges/visibility")
async def tch_set_challenge_visibility(payload: ChallengeVisibilityRequest, _=Depends(require_admin)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    try:
        challenge = manager._find_by_code(payload.code)
    except KeyError:
        _err(f"Challenge {payload.code} not found", 404)
        return

    set_challenge_enabled(challenge.get_benchmark_id(), payload.enabled)
    stopped = False
    if not payload.enabled:
        stopped = await _stop_instance_if_running(payload.code)

    msg = ("已开启" if payload.enabled else "已关闭") + ("，并停止运行中的实例" if stopped else "")
    return _ok({
        "code": payload.code,
        "enabled": payload.enabled,
        "stopped": stopped,
    }, msg)


class LevelVisibilityRequest(PydanticBaseModel):
    level: int
    enabled: bool


@app.post("/api/level_visibility")
async def tch_set_level_visibility(payload: LevelVisibilityRequest, _=Depends(require_admin)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    bm_ids: list[str] = []
    affected_codes: list[str] = []
    for c in manager.challenges:
        if manager.get_level_for_challenge(c) != payload.level:
            continue
        bm_ids.append(c.get_benchmark_id())
        affected_codes.append(c.challenge_code)

    if not bm_ids:
        return _ok({"affected": 0, "stopped": 0}, "该 level 没有题目")

    set_challenges_enabled_bulk(bm_ids, payload.enabled)

    stopped_count = 0
    if not payload.enabled:
        for code in affected_codes:
            if await _stop_instance_if_running(code):
                stopped_count += 1

    action = "开启" if payload.enabled else "关闭"
    extra = f"，并停止 {stopped_count} 个运行中实例" if stopped_count else ""
    return _ok({
        "level": payload.level,
        "enabled": payload.enabled,
        "affected": len(bm_ids),
        "stopped": stopped_count,
    }, f"Level {payload.level} 已{action} {len(bm_ids)} 道题{extra}")


@app.get("/api/challenges/visibility")
async def tch_get_challenge_visibility(_=Depends(require_admin)):
    """Web UI 用,返回所有 benchmark_id 的当前开关状态。"""
    if manager is None:
        _err("Server not initialized", 503)
        return
    explicit = get_challenge_visibility()
    visibility = {}
    for c in manager.challenges:
        bm_id = c.get_benchmark_id()
        visibility[c.challenge_code] = {
            "benchmark_id": bm_id,
            "enabled": explicit.get(bm_id, True),
        }
    return _ok({"visibility": visibility})


@app.post("/api/toggle_level_gate")
async def tch_toggle_level_gate(_=Depends(require_admin)):
    if manager is None:
        _err("Server not initialized", 503)
        return
    manager.no_level_gate = not manager.no_level_gate
    set_setting("no_level_gate", "1" if manager.no_level_gate else "0")
    return _ok({"no_level_gate": manager.no_level_gate})


class LevelGateConfigRequest(PydanticBaseModel):
    mode: str
    threshold: int


@app.get("/api/level_gate_config")
async def get_level_gate_config_api(_=Depends(require_admin)):
    return _ok(get_level_gate_config())


@app.post("/api/level_gate_config")
async def set_level_gate_config_api(payload: LevelGateConfigRequest, _=Depends(require_admin)):
    try:
        config = set_level_gate_config(payload.mode, payload.threshold)
    except ValueError as e:
        _err(str(e), 400)
        return
    return _ok(config)


@app.get("/api/settings/instance_timeout")
async def get_timeout_settings(_=Depends(require_admin)):
    config = get_instance_timeout_config()
    return _ok({"level_1": config[1], "level_2": config[2], "level_3": config[3]})


class InstanceTimeoutRequest(PydanticBaseModel):
    level_1: int
    level_2: int
    level_3: int


@app.post("/api/settings/instance_timeout")
async def set_timeout_settings(payload: InstanceTimeoutRequest, _=Depends(require_admin)):
    if payload.level_1 < 60 or payload.level_2 < 60 or payload.level_3 < 60:
        _err("超时时间不能小于 60 秒", 400)
        return
    set_instance_timeout_config({1: payload.level_1, 2: payload.level_2, 3: payload.level_3})
    return _ok(None, "实例超时配置已保存")


@app.get("/api/runtime_dir")
async def get_runtime_dir_api(_=Depends(require_admin)):
    return _ok({"runtime_dir": get_setting("runtime_dir", "./runtime")})


class RuntimeDirRequest(PydanticBaseModel):
    runtime_dir: str


@app.post("/api/runtime_dir")
async def set_runtime_dir_api(payload: RuntimeDirRequest, _=Depends(require_admin)):
    path = payload.runtime_dir.strip()
    if not path:
        _err("路径不能为空", 400)
        return
    set_setting("runtime_dir", path)
    return _ok({"runtime_dir": path})


@app.get("/api/settings/vnc_password")
async def get_vnc_password_api(_=Depends(require_admin)):
    return _ok({"vnc_password": get_setting("vnc_password", "VncAdmin2024!")})


class VncPasswordRequest(PydanticBaseModel):
    password: str


@app.post("/api/settings/vnc_password")
async def set_vnc_password_api(payload: VncPasswordRequest, _=Depends(require_admin)):
    pwd = payload.password.strip()
    if not pwd:
        _err("密码不能为空", 400)
        return
    set_setting("vnc_password", pwd)
    from benchmark_platform.web.vnc_proxy import reload_auth
    reload_auth()
    return _ok({"vnc_password": pwd}, "已保存")


@app.get("/api/settings/win_iso")
async def get_win_iso_api(_=Depends(require_admin)):
    return _ok({"win2022_iso_path": get_setting("win2022_iso_path", "")})


class WinIsoRequest(PydanticBaseModel):
    path: str


@app.post("/api/settings/win_iso")
async def set_win_iso_api(payload: WinIsoRequest, _=Depends(require_admin)):
    path = payload.path.strip()
    if not path:
        _err("路径不能为空", 400)
        return
    if not os.path.isfile(path):
        _err(f"文件不存在: {path}", 400)
        return
    set_setting("win2022_iso_path", path)
    return _ok({"win2022_iso_path": path}, "已保存")


# ── Admin VNC Proxy API ──────────────────────────────────────────────────────

class VncToggleRequest(PydanticBaseModel):
    benchmark_id: str


@app.post("/api/vnc/enable")
async def vnc_enable_api(payload: VncToggleRequest, _=Depends(require_admin)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    from benchmark_platform.web.vnc_proxy import enable_vnc
    vms = enable_vnc(payload.benchmark_id, manager.runtime_dir)
    if vms is None:
        _err("无法获取容器 IP，请确认实例正在运行", 400)
        return
    return _ok({"vms": vms}, "VNC 代理已开启")


@app.post("/api/vnc/disable")
async def vnc_disable_api(payload: VncToggleRequest, _=Depends(require_admin)):
    from benchmark_platform.web.vnc_proxy import disable_vnc
    disable_vnc(payload.benchmark_id)
    return _ok(None, "VNC 代理已关闭")


@app.get("/api/vnc/status")
async def vnc_status_api(_=Depends(require_admin)):
    from benchmark_platform.web.vnc_proxy import get_active_proxies
    return _ok({"active": get_active_proxies()})


class BatchLevelRequest(PydanticBaseModel):
    level: int


@app.post("/api/start_level")
async def tch_start_level(payload: BatchLevelRequest, _=Depends(require_admin)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    to_start = []
    for c in manager.challenges:
        if manager.get_level_for_challenge(c) != payload.level:
            continue
        if not is_challenge_enabled(c.get_benchmark_id()):
            continue
        if c.unsupported:
            continue
        if c.solved:
            continue
        if manager.get_instance_status(c.challenge_code) in ("running", "unhealthy"):
            continue
        to_start.append(c.challenge_code)

    if not to_start:
        return _ok({"started": 0, "total": 0}, "没有需要启动的实例")

    def _start_in_background(codes: list[str]) -> None:
        for code in codes:
            try:
                manager.start_challenge_instance(code)
            except Exception as e:
                logger.error("batch start failed", challenge_code=code, error=str(e))
        app.state.batch_starting = False

    app.state.batch_starting = True
    threading.Thread(target=_start_in_background, args=(to_start,), daemon=True).start()
    return _ok({"started": 0, "total": len(to_start)}, f"正在启动 {len(to_start)} 个实例...")


@app.post("/api/stop_level")
async def tch_stop_level(payload: BatchLevelRequest, _=Depends(require_admin)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    to_stop = []
    for c in manager.challenges:
        if manager.get_level_for_challenge(c) != payload.level:
            continue
        if manager.get_instance_status(c.challenge_code) not in ("running", "unhealthy"):
            continue
        to_stop.append(c.challenge_code)

    if not to_stop:
        return _ok({"stopped": 0}, "没有运行中的实例")

    stopped = []
    for code in to_stop:
        try:
            await asyncio.to_thread(manager.stop_challenge_instance, code)
            stopped.append(code)
        except Exception:
            pass

    return _ok({"stopped": len(stopped)}, f"已停止 {len(stopped)} 个实例")


@app.get("/api/instance_statuses")
async def tch_instance_statuses(request: Request, _=Depends(require_admin)):
    """Lightweight endpoint for polling instance statuses.

    Agent callers (with Agent-Token) get only enabled challenges.
    Web UI callers (no Agent-Token, browser session) get all challenges so the
    challenges page can keep refreshing disabled cards too.
    """
    if manager is None:
        _err("Server not initialized", 503)
        return

    agent_view = request.headers.get("Agent-Token") is not None

    statuses = {}
    for c in manager.challenges:
        bm_id = c.get_benchmark_id()
        enabled = is_challenge_enabled(bm_id)
        if agent_view and not enabled:
            continue
        started_at, expires_at = manager.get_instance_timestamps(c.challenge_code)
        statuses[c.challenge_code] = {
            "status": manager.get_instance_status(c.challenge_code),
            "benchmark_id": bm_id,
            "level": manager.get_level_for_challenge(c),
            "solved": c.solved,
            "enabled": enabled,
            "started_at": started_at,
            "expires_at": expires_at,
        }
    return _ok({"statuses": statuses, "batch_starting": getattr(app.state, "batch_starting", False)})


@app.get("/api/instance_logs")
async def tch_instance_logs(benchmark_id: str, offset: int = 0, _=Depends(require_admin)):
    """Return compose logs for a challenge instance (used by Web UI log panel)."""
    if manager is None:
        _err("Server not initialized", 503)
        return

    challenge = None
    for c in manager.challenges:
        if c.get_benchmark_id() == benchmark_id:
            challenge = c
            break
    if challenge is None:
        _err(f"Challenge {benchmark_id} not found", 404)
        return

    status = manager.get_instance_status(challenge.challenge_code)
    logs, total = manager.get_instance_logs(benchmark_id, offset)
    return _ok({"status": status, "logs": logs, "total": total})


# ── Prebuild/Cache API ──────────────────────────────────────────────────────

class PrebuildStartRequest(PydanticBaseModel):
    concurrency: int = 1
    codes: list[str] | None = None


@app.post("/api/prebuild/start")
async def prebuild_start(payload: PrebuildStartRequest, _=Depends(require_admin)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    from benchmark_platform.web.prebuild_manager import PrebuildManager

    # Create or reuse existing manager
    prebuild_mgr = getattr(app.state, "prebuild_manager", None)
    if prebuild_mgr is None or not prebuild_mgr.is_running:
        prebuild_mgr = PrebuildManager(manager.challenges, manager.benchmark_folders)
        prebuild_mgr.check_cached()
        app.state.prebuild_manager = prebuild_mgr

    if not prebuild_mgr.is_running:
        concurrency = max(1, min(3, payload.concurrency))
        prebuild_mgr.start(concurrency, codes=payload.codes)

    return _ok(None, "预构建已启动")


@app.post("/api/prebuild/stop")
async def prebuild_stop(_=Depends(require_admin)):
    prebuild_mgr = getattr(app.state, "prebuild_manager", None)
    if prebuild_mgr is None:
        _err("No prebuild in progress", 400)
        return
    prebuild_mgr.stop()
    return _ok(None, "已发送停止信号")


@app.get("/api/prebuild/status")
async def prebuild_status(_=Depends(require_admin)):
    prebuild_mgr = getattr(app.state, "prebuild_manager", None)
    if prebuild_mgr is None:
        # No manager yet — return empty state
        if manager is None:
            return _ok({"challenges": [], "cached_count": 0, "total_count": 0, "building": False})
        # Create one on-the-fly for status check
        from benchmark_platform.web.prebuild_manager import PrebuildManager
        prebuild_mgr = PrebuildManager(manager.challenges, manager.benchmark_folders)
        prebuild_mgr.check_cached()
        app.state.prebuild_manager = prebuild_mgr

    return _ok({
        "challenges": prebuild_mgr.get_status(),
        "cached_count": prebuild_mgr.cached_count,
        "total_count": prebuild_mgr.total_count,
        "building": prebuild_mgr.is_running,
    })


class PrebuildRemoveRequest(PydanticBaseModel):
    code: str


class PrebuildRemoveBatchRequest(PydanticBaseModel):
    codes: list[str]


@app.post("/api/prebuild/remove")
async def prebuild_remove(payload: PrebuildRemoveRequest, _=Depends(require_admin)):
    prebuild_mgr = getattr(app.state, "prebuild_manager", None)
    if prebuild_mgr is None:
        _err("Prebuild manager not initialized", 400)
        return

    ok, msg = prebuild_mgr.remove_images(payload.code)
    if not ok:
        _err(msg, 400)
        return
    return _ok(None, msg)


@app.post("/api/prebuild/remove_batch")
async def prebuild_remove_batch(payload: PrebuildRemoveBatchRequest, _=Depends(require_admin)):
    prebuild_mgr = getattr(app.state, "prebuild_manager", None)
    if prebuild_mgr is None:
        _err("Prebuild manager not initialized", 400)
        return

    removed = 0
    failed = 0
    for code in payload.codes:
        ok, _ = prebuild_mgr.remove_images(code)
        if ok:
            removed += 1
        else:
            failed += 1
    return _ok({"removed": removed, "failed": failed}, f"已删除 {removed} 个题目的镜像")


@app.post("/api/prebuild/remove_all")
async def prebuild_remove_all(_=Depends(require_admin)):
    prebuild_mgr = getattr(app.state, "prebuild_manager", None)
    if prebuild_mgr is None:
        _err("Prebuild manager not initialized", 400)
        return

    removed, failed = prebuild_mgr.remove_all_images()
    return _ok({"removed": removed, "failed": failed}, f"已清理 {removed} 个题目的镜像")


# -- Challenge Store API -------------------------------------------------------

@app.get("/api/store/manifest")
async def store_manifest(source: str = "all", _=Depends(require_admin)):
    from benchmark_platform.web.store import ChallengeStore
    if not hasattr(app.state, '_challenge_store'):
        app.state._challenge_store = ChallengeStore(challenges_dir=app.state.challenges_dir)
    store = app.state._challenge_store

    if source == "local":
        challenges = store.get_local_challenges()
    elif source == "remote":
        try:
            challenges = store.get_remote_challenges()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch remote manifest: {e}")
    else:
        challenges = store.get_local_challenges()
        try:
            remote = store.get_remote_challenges()
            challenges = store.merge_challenges(challenges, remote)
        except Exception:
            pass

    return {"code": 0, "data": {"challenges": challenges}}


@app.post("/api/store/sizes")
async def store_sizes(body: dict, _=Depends(require_admin)):
    """Calculate directory sizes for challenges that have no stored size metadata."""
    import asyncio
    from pathlib import Path as _Path

    items = body.get("items", [])
    if not items:
        return {"code": 0, "data": {"sizes": {}}}

    challenges_dir: _Path = app.state.challenges_dir

    def _calc_dir_size(category: str, name: str) -> int:
        d = challenges_dir / category / name
        if not d.is_dir():
            return 0
        total = 0
        for f in d.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
        return total

    loop = asyncio.get_event_loop()
    sizes = {}
    for item in items[:500]:
        cat = item.get("category", "")
        nm = item.get("name", "")
        if cat and nm:
            key = f"{cat}/{nm}"
            sizes[key] = await loop.run_in_executor(None, _calc_dir_size, cat, nm)

    return {"code": 0, "data": {"sizes": sizes}}


@app.post("/api/store/download")
def store_download(body: dict, _=Depends(require_admin)):
    from benchmark_platform.web.store import ChallengeStore
    category = body.get("category")
    name = body.get("name")
    asset = body.get("asset")
    size = body.get("size", 0)
    if not all([category, name, asset]):
        raise HTTPException(status_code=400, detail="category, name, asset required")

    store = ChallengeStore(
        challenges_dir=app.state.challenges_dir,
    )
    try:
        store.download_challenge(category, name, asset, size=size)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Download failed: {e}")

    _auto_reload_challenges()
    return {"code": 0, "message": f"{category}/{name} downloaded"}


@app.post("/api/store/delete")
async def store_delete(body: dict, _=Depends(require_admin)):
    from benchmark_platform.web.store import ChallengeStore
    category = body.get("category")
    name = body.get("name")
    if not all([category, name]):
        raise HTTPException(status_code=400, detail="category, name required")

    store = ChallengeStore(
        challenges_dir=app.state.challenges_dir,
    )
    try:
        store.delete_challenge(category, name)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Delete failed: {e}")
    return {"code": 0, "message": f"{category}/{name} deleted"}


@app.post("/api/store/download-all")
async def store_download_all(_=Depends(require_admin)):
    from benchmark_platform.web.store import ChallengeStore
    store = ChallengeStore(
        challenges_dir=app.state.challenges_dir,
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

    _auto_reload_challenges()
    return {"code": 0, "data": results}


@app.post("/api/store/import")
async def store_import(files: list[UploadFile] = File(...), _=Depends(require_admin)):
    from benchmark_platform.web.store import ChallengeStore
    store = ChallengeStore(
        challenges_dir=app.state.challenges_dir,
    )
    results = []
    for f in files:
        if not f.filename or not f.filename.endswith(".zip"):
            results.append({"name": f.filename, "status": "error", "detail": "must be .zip"})
            continue
        try:
            data = await f.read()
            category, name = store.import_challenge(data, f.filename)
            results.append({"name": f"{category}/{name}", "status": "ok"})
        except Exception as e:
            results.append({"name": f.filename, "status": "error", "detail": str(e)})

    _auto_reload_challenges()
    return {"code": 0, "data": results}


app_cli = typer.Typer()


@app_cli.command()
def serve(
    benchmark_folder: list[Path] = typer.Option(
        [],
        "--benchmark-folder",
        help="Benchmark folder to load (repeat to add multiple folders). "
             "Each subdirectory with benchmark.json is loaded as a challenge.",
    ),
    benchmark_ids: list[str] = typer.Option(
        [],
        "--benchmark-id",
        "-i",
        help="Filter by benchmark ID (e.g. XBEN-001-24). Empty = load all.",
    ),
    challenges_dir: Path = typer.Option(
        Path("challenges"),
        "--challenges-dir",
        help="Root directory for challenge store downloads.",
    ),
    admin_token: str = typer.Option(
        "",
        "--admin-token",
        envvar="ADMIN_TOKEN",
        help="Admin token for Web UI login. If empty, a random token is generated each startup.",
    ),
    no_level_gate: bool = typer.Option(
        False,
        "--no-level-gate",
        help="Disable level gate — all challenges visible and startable immediately.",
    ),
    host: str = typer.Option(
        "0.0.0.0",
        help="Host to bind to",
    ),
    port: int = typer.Option(8088, help="Port to bind to"),
    public_accessible_host: str = typer.Option(
        "localhost",
        help="Public accessible host for entrypoint URLs",
    ),
):
    global CHALLENGES, manager

    if not benchmark_folder:
        logger.error("no benchmark folder provided", action="serve")
        raise typer.Exit(1)

    logger.info(
        "starting server",
        action="serve",
        benchmark_folders=[str(f) for f in benchmark_folder],
        benchmark_ids=benchmark_ids,
        no_level_gate=no_level_gate,
        host=host,
        port=port,
        public_accessible_host=public_accessible_host,
    )

    init_db()

    # CLI --no-level-gate only takes effect as override; otherwise read from DB
    if no_level_gate:
        set_setting("no_level_gate", "1")
    effective_no_level_gate = get_setting("no_level_gate", "0") == "1"

    manager = ChallengeManager(
        benchmark_folders=benchmark_folder,
        benchmark_ids=benchmark_ids,
        public_accessible_host=public_accessible_host,
        no_level_gate=effective_no_level_gate,
        runtime_dir=Path(get_setting("runtime_dir", "./runtime")),
    )
    manager.start()
    CHALLENGES = manager.challenges

    # Inject manager reference into MCP server module
    from benchmark_platform.mcp_server import set_manager
    set_manager(manager)

    effective_token = admin_token if admin_token else secrets.token_hex(16)
    default_team = get_or_create_default_team(effective_token)

    from rich.console import Console
    console = Console()
    console.print(f"\n  [bold green]Admin Token:[/bold green] {default_team['token']}\n")

    # Sync solved state from DB to Challenge objects
    team_progress = get_team_progress(default_team["id"])
    for c in manager.challenges:
        bm_id = c.get_benchmark_id()
        progress = team_progress.get(bm_id, {})
        if progress:
            for fs in c.flag_states:
                if progress.get(fs.id):
                    fs.solved = True
            if not c.flag_states:
                c.solved = bool(progress)
            elif all(fs.solved for fs in c.flag_states):
                c.solved = True

    submission_store = SubmissionStore(
        log_path=Path("logs/submissions.jsonl"),
    )
    app.state.manager = manager
    app.state.submission_store = submission_store
    app.state.challenges_dir = challenges_dir

    manager.print_summary_table()

    logger.info("binding uvicorn", action="serve", host=host, port=port)
    try:
        uvicorn.run(app, host=host, port=port)
    finally:
        manager.stop()


if __name__ == '__main__':
    app_cli()
