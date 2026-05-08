import atexit
import signal
from pathlib import Path
from typing import NoReturn

import typer
import uvicorn
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import RedirectResponse

from pydantic import BaseModel as PydanticBaseModel

from benchmark_platform.base import Challenge
from benchmark_platform.base import CompetitionStage
from benchmark_platform.base import GetChallengeHintResponse
from benchmark_platform.base import GetChallengesResponse
from benchmark_platform.base import SubmitAnswerRequest
from benchmark_platform.base import SubmitAnswerResponse
from benchmark_platform.utils.challenge import ChallengeManager
from benchmark_platform.utils.logger import get_logger


app = FastAPI()

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
    return RedirectResponse(url='/docs')


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
        if status == "running":
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
            "flag_count": 1,
            "flag_got_count": 1 if c.solved else 0,
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

    if manager.get_instance_status(payload.code) == "running":
        entrypoints = [f"{manager.public_accessible_host}:{p}" for p in challenge.target_info.port]
        return _ok(entrypoints, "赛题实例已在运行中")

    try:
        entrypoints = manager.start_challenge_instance(payload.code)
    except Exception as e:
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

    if manager.get_instance_status(payload.code) != "running":
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
        return  # unreachable, but makes control flow explicit

    try:
        challenge = manager._find_by_code(payload.code)
    except KeyError:
        _err(f"Challenge {payload.code} not found", 404)
        return  # unreachable, but makes control flow explicit

    if manager.get_instance_status(payload.code) != "running":
        _err("赛题实例未运行", 400)
        return  # unreachable, but makes control flow explicit

    try:
        expected = challenge.get_expected_answer()
    except Exception as e:
        _err(f"Failed to get expected answer: {e}", 500)
        return  # unreachable, but makes control flow explicit

    is_correct = expected == payload.flag
    if is_correct:
        challenge.solved = True

    return _ok({
        "correct": is_correct,
        "message": "恭喜！答案正确" if is_correct else "答案错误，请继续尝试",
        "flag_count": 1,
        "flag_got_count": 1 if challenge.solved else 0,
    })


class HintRequest(PydanticBaseModel):
    code: str


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

    if manager.get_instance_status(payload.code) != "running":
        _err("请先启动赛题实例", 400)
        return  # unreachable, but makes control flow explicit

    try:
        hint = challenge.get_hint()
    except Exception as e:
        _err(f"Failed to get hint: {e}", 500)
        return  # unreachable, but makes control flow explicit

    challenge.hint_viewed = True
    return _ok({"code": payload.code, "hint_content": hint})


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
    port: int = typer.Option(8000, help="Port to bind to"),
    public_accessible_host: str = typer.Option(
        "host.docker.internal",
        help="Public accessible host",
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
    manager.print_summary_table()

    logger.info("binding uvicorn", action="serve", host=host, port=port)
    try:
        uvicorn.run(app, host=host, port=port)
    finally:
        manager.stop()


if __name__ == '__main__':
    app_cli()
