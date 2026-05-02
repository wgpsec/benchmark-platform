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
    benchmark_ids: list[int] = typer.Option(
        list(range(1, 5)),
        '-i', help='Benchmark IDs to serve',
    ),
    host: str = typer.Option(
        '0.0.0.0',
        help='Host to bind to',
    ),
    port: int = typer.Option(8000, help='Port to bind to'),
    public_accessible_host: str = typer.Option(
        'host.docker.internal',
        help='Public accessible host',
    ),
    xbow_benchmark_folder: Path = typer.Option(
        ...,
        help='Path to the Xbow benchmark folder (e.g., validation-benchmarks/benchmarks)',
    ),
):
    global CHALLENGES, manager
    logger.info(
        'starting server', action='serve', xbow_benchmark_folder=xbow_benchmark_folder,
        benchmark_ids=benchmark_ids, host=host, port=port, public_accessible_host=public_accessible_host,
    )
    benchmark_str_ids = [
        f'XBEN-{benchmark_id:03d}-24' for benchmark_id in benchmark_ids
    ]
    logger.info(
        'initializing benchmark challenges',
        action='serve', benchmark_ids=benchmark_str_ids,
    )

    # 创建并启动挑战管理器
    manager = ChallengeManager(
        xbow_benchmark_folder=xbow_benchmark_folder,
        benchmark_ids=benchmark_str_ids,
        public_accessible_host=public_accessible_host,
    )
    manager.start()
    CHALLENGES = manager.challenges
    manager.print_summary_table()

    logger.info('starting server', action='serve', host=host, port=port)
    try:
        uvicorn.run(app, host=host, port=port)
    finally:
        # 服务器停止时清理挑战
        manager.stop()


if __name__ == '__main__':
    app_cli()
