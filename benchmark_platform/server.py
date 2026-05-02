import atexit
import signal
from pathlib import Path

import typer
import uvicorn
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import RedirectResponse

from benchmark_platform.base import Challenge
from benchmark_platform.base import CompetitionStage
from benchmark_platform.base import GetChallengeHintResponse
from benchmark_platform.base import GetChallengesResponse
from benchmark_platform.base import SubmitAnswerRequest
from benchmark_platform.base import SubmitAnswerResponse
from benchmark_platform.utils.challenge import ChallengeManager
from benchmark_platform.utils.logger import get_logger


app = FastAPI()
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
