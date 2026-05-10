import atexit
import signal
from pathlib import Path
from typing import NoReturn

import typer
import uvicorn
from fastapi import FastAPI
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
async def tch_get_challenges():
    if manager is None:
        _err("Server not initialized", 503)
        return  # unreachable, but makes control flow explicit

    all_challenges = manager.challenges
    challenge_list = []
    for c in all_challenges:
        bm = c.get_benchmark()
        status = manager.get_instance_status(c.challenge_code)
        entrypoint = None
        if status in ("running", "unhealthy"):
            entrypoint = [f"{manager.public_accessible_host}:{p}" for p in c.target_info.port]
        challenge_list.append({
            "benchmark_id": c.get_benchmark_id(),
            "title": bm.name,
            "code": c.challenge_code,
            "difficulty": c.difficulty.value,
            "description": bm.description,
            "level": bm.level,
            "total_score": c.points,
            "total_got_score": c.points if c.solved else 0,
            "flag_count": c.flag_count,
            "flag_got_count": c.solved_count,
            "flags": [
                {"id": fs.id, "route": fs.route, "description": fs.description, "solved": fs.solved}
                for fs in c.flag_states
            ] if c.flag_states else None,
            "hint_viewed": c.hint_viewed,
            "instance_status": status,
            "entrypoint": entrypoint,
        })

    solved = sum(1 for c in all_challenges if c.solved)
    return _ok({
        "total_challenges": len(all_challenges),
        "solved_challenges": solved,
        "challenges": challenge_list,
    })


class StartChallengeRequest(PydanticBaseModel):
    code: str


@app.post("/api/start_challenge")
async def tch_start_challenge(payload: StartChallengeRequest):
    if manager is None:
        _err("Server not initialized", 503)
        return  # unreachable, but makes control flow explicit

    try:
        challenge = manager._find_by_code(payload.code)
    except KeyError:
        _err(f"Challenge {payload.code} not found", 404)
        return  # unreachable, but makes control flow explicit

    if challenge.solved:
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
async def tch_stop_challenge(payload: StopChallengeRequest):
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
async def tch_submit(payload: SubmitFlagRequest):
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
        if challenge.flag_states:
            from datetime import datetime, timezone
            for fs in challenge.flag_states:
                if fs.id == matched_flag_id and not fs.solved:
                    fs.solved = True
                    fs.solved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            challenge.solved = all(fs.solved for fs in challenge.flag_states)
        else:
            challenge.solved = True

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
            points=challenge.points if is_correct and matched_flag_id else 0,
        ))

    return _ok({
        "correct": is_correct,
        "flag_id": matched_flag_id,
        "message": "恭喜！答案正确" if is_correct else "答案错误，请继续尝试",
        "flag_count": challenge.flag_count,
        "flag_got_count": challenge.solved_count,
        "all_solved": challenge.solved,
    })


class HintRequest(PydanticBaseModel):
    code: str


@app.get("/api/challenges/{code}/progress")
async def tch_get_progress(code: str):
    if manager is None:
        _err("Server not initialized", 503)
        return

    try:
        challenge = manager._find_by_code(code)
    except KeyError:
        _err(f"Challenge {code} not found", 404)
        return

    if challenge.flag_states:
        flags_progress = [
            {"id": fs.id, "route": fs.route, "solved": fs.solved, "solved_at": fs.solved_at}
            for fs in challenge.flag_states
        ]
    else:
        flags_progress = [
            {"id": "default", "route": "/", "solved": challenge.solved, "solved_at": None}
        ]

    return _ok({
        "challenge_code": code,
        "flags": flags_progress,
        "solved_count": challenge.solved_count,
        "total_count": challenge.flag_count,
        "all_solved": challenge.solved,
    })


@app.post("/api/hint")
async def tch_hint(payload: HintRequest):
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

    challenge.hint_viewed = True
    return _ok({"code": payload.code, "hint_content": hint})


@app.post("/api/stop_all")
async def tch_stop_all():
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
