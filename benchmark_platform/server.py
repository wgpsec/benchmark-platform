from __future__ import annotations

import atexit
import signal
from pathlib import Path
from typing import NoReturn

import typer
import uvicorn
from fastapi import Depends, FastAPI
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
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
from benchmark_platform.web.submission_store import SubmissionStore
from benchmark_platform.auth import get_current_team
from benchmark_platform.db import (
    init_db, get_or_create_default_team,
    mark_flag_solved, get_team_solved_count,
    is_hint_viewed, mark_hint_viewed, get_team_progress,
)


app = FastAPI()
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(web_router, prefix="/web")

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

@app.get("/api/challenges")
async def tch_get_challenges(team: dict = Depends(get_current_team)):
    if manager is None:
        _err("Server not initialized", 503)
        return  # unreachable, but makes control flow explicit

    all_challenges = manager.challenges
    team_progress = get_team_progress(team["id"])
    challenge_list = []
    total_solved_challenges = 0
    for c in all_challenges:
        bm = c.get_benchmark()
        status = manager.get_instance_status(c.challenge_code)
        entrypoint = None
        if status in ("running", "unhealthy"):
            entrypoint = [f"{manager.public_accessible_host}:{p}" for p in c.target_info.port]

        team_solved = get_team_solved_count(team["id"], c.challenge_code)
        all_solved = team_solved >= c.flag_count
        hint_viewed = is_hint_viewed(team["id"], c.challenge_code)

        if all_solved:
            total_solved_challenges += 1

        if c.flag_count > 0:
            per_flag_score = c.points // c.flag_count
            got_score = per_flag_score * team_solved
        else:
            got_score = c.points if all_solved else 0

        # Per-flag solved status from DB
        progress_for_challenge = team_progress.get(c.challenge_code, {})
        flags_info = None
        if c.flag_states:
            flags_info = [
                {"id": fs.id, "route": fs.route, "description": fs.description, "solved": progress_for_challenge.get(fs.id, False)}
                for fs in c.flag_states
            ]

        challenge_list.append({
            "benchmark_id": c.get_benchmark_id(),
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
        })

    return _ok({
        "current_level": manager.get_current_level(),
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

    team_solved = get_team_solved_count(team["id"], challenge.challenge_code)
    if team_solved >= challenge.flag_count:
        return _ok({"already_completed": True}, "该赛题已全部完成，无需再启动实例")

    if manager.get_instance_status(payload.code) in ("running", "unhealthy"):
        entrypoints = [f"{manager.public_accessible_host}:{p}" for p in challenge.target_info.port]
        return _ok(entrypoints, "赛题实例已在运行中")

    try:
        entrypoints = manager.start_challenge_instance(payload.code)
    except Exception as e:
        logger.error("start_challenge failed", action="api", challenge_code=payload.code, error=str(e))
        _err(f"赛题启动失败: {e}", 502)
        return  # unreachable, but makes control flow explicit

    return _ok(entrypoints, "赛题实例启动成功")


class StopChallengeRequest(PydanticBaseModel):
    code: str


@app.post("/api/stop_challenge")
async def tch_stop_challenge(payload: StopChallengeRequest, team: dict = Depends(get_current_team)):
    if manager is None:
        _err("Server not initialized", 503)
        return  # unreachable, but makes control flow explicit

    try:
        manager._find_by_code(payload.code)
    except KeyError:
        _err(f"Challenge {payload.code} not found", 404)
        return  # unreachable, but makes control flow explicit

    if manager.get_instance_status(payload.code) not in ("running", "unhealthy"):
        _err("赛题实例未运行", 400)
        return  # unreachable, but makes control flow explicit

    try:
        manager.stop_challenge_instance(payload.code)
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
        mark_flag_solved(team["id"], challenge.challenge_code, matched_flag_id)

    team_solved = get_team_solved_count(team["id"], challenge.challenge_code)
    all_solved = team_solved >= challenge.flag_count

    # Record submission
    from datetime import datetime, timezone as _tz
    from benchmark_platform.web.submission_store import SubmissionRecord
    if hasattr(app.state, 'submission_store') and app.state.submission_store is not None:
        bm = challenge.get_benchmark()
        app.state.submission_store.add(SubmissionRecord(
            timestamp=datetime.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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

    team_progress = get_team_progress(team["id"])
    progress_for_challenge = team_progress.get(code, {})
    team_solved = get_team_solved_count(team["id"], code)
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

    if manager.get_instance_status(payload.code) not in ("running", "unhealthy"):
        _err("请先启动赛题实例", 400)
        return  # unreachable, but makes control flow explicit

    try:
        hint = challenge.get_hint()
    except Exception as e:
        _err(f"Failed to get hint: {e}", 500)
        return  # unreachable, but makes control flow explicit

    mark_hint_viewed(team["id"], payload.code)
    return _ok({"code": payload.code, "hint_content": hint})


@app.post("/api/stop_all")
async def tch_stop_all(team: dict = Depends(get_current_team)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    stopped = []
    for c in manager.challenges:
        if manager.get_instance_status(c.challenge_code) in ("running", "unhealthy"):
            try:
                manager.stop_challenge_instance(c.challenge_code)
                stopped.append(c.challenge_code)
            except Exception:
                pass
    return _ok({"stopped_count": len(stopped)}, f"已停止 {len(stopped)} 个实例")


@app.post("/api/toggle_level_gate")
async def tch_toggle_level_gate():
    if manager is None:
        _err("Server not initialized", 503)
        return
    manager.no_level_gate = not manager.no_level_gate
    return _ok({"no_level_gate": manager.no_level_gate})


class BatchLevelRequest(PydanticBaseModel):
    level: int


@app.post("/api/start_level")
async def tch_start_level(payload: BatchLevelRequest):
    if manager is None:
        _err("Server not initialized", 503)
        return

    started = []
    errors = []
    for c in manager.challenges:
        if manager.get_level_for_challenge(c) != payload.level:
            continue
        if c.solved:
            continue
        if manager.get_instance_status(c.challenge_code) in ("running", "unhealthy"):
            continue
        try:
            manager.start_challenge_instance(c.challenge_code)
            started.append(c.challenge_code)
        except Exception as e:
            errors.append(c.challenge_code)
            logger.error("batch start failed", challenge_code=c.challenge_code, error=str(e))

    return _ok({"started": len(started), "errors": len(errors)}, f"已启动 {len(started)} 个实例")


@app.post("/api/stop_level")
async def tch_stop_level(payload: BatchLevelRequest):
    if manager is None:
        _err("Server not initialized", 503)
        return

    stopped = []
    for c in manager.challenges:
        if manager.get_level_for_challenge(c) != payload.level:
            continue
        if manager.get_instance_status(c.challenge_code) not in ("running", "unhealthy"):
            continue
        try:
            manager.stop_challenge_instance(c.challenge_code)
            stopped.append(c.challenge_code)
        except Exception:
            pass

    return _ok({"stopped": len(stopped)}, f"已停止 {len(stopped)} 个实例")


# ── Prebuild/Cache API ──────────────────────────────────────────────────────

class PrebuildStartRequest(PydanticBaseModel):
    concurrency: int = 1


@app.post("/api/prebuild/start")
async def prebuild_start(payload: PrebuildStartRequest):
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
        prebuild_mgr.start(concurrency)

    return _ok(None, "预构建已启动")


@app.post("/api/prebuild/stop")
async def prebuild_stop():
    prebuild_mgr = getattr(app.state, "prebuild_manager", None)
    if prebuild_mgr is None:
        _err("No prebuild in progress", 400)
        return
    prebuild_mgr.stop()
    return _ok(None, "已发送停止信号")


@app.get("/api/prebuild/status")
async def prebuild_status():
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


@app.post("/api/prebuild/remove")
async def prebuild_remove(payload: PrebuildRemoveRequest):
    prebuild_mgr = getattr(app.state, "prebuild_manager", None)
    if prebuild_mgr is None:
        _err("Prebuild manager not initialized", 400)
        return

    ok, msg = prebuild_mgr.remove_images(payload.code)
    if not ok:
        _err(msg, 400)
        return
    return _ok(None, msg)


@app.post("/api/prebuild/remove_all")
async def prebuild_remove_all():
    prebuild_mgr = getattr(app.state, "prebuild_manager", None)
    if prebuild_mgr is None:
        _err("Prebuild manager not initialized", 400)
        return

    removed, failed = prebuild_mgr.remove_all_images()
    return _ok({"removed": removed, "failed": failed}, f"已清理 {removed} 个题目的镜像")


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

    manager = ChallengeManager(
        benchmark_folders=benchmark_folder,
        benchmark_ids=benchmark_ids,
        public_accessible_host=public_accessible_host,
        no_level_gate=no_level_gate,
    )
    manager.start()
    CHALLENGES = manager.challenges

    init_db()
    get_or_create_default_team()

    submission_store = SubmissionStore(
        log_path=Path("logs/submissions.jsonl"),
    )
    app.state.manager = manager
    app.state.submission_store = submission_store

    manager.print_summary_table()

    logger.info("binding uvicorn", action="serve", host=host, port=port)
    try:
        uvicorn.run(app, host=host, port=port)
    finally:
        manager.stop()


if __name__ == '__main__':
    app_cli()
