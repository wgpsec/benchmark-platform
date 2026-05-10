"""Tests for level gate logic in ChallengeManager."""
from benchmark_platform.base import Challenge, Difficulty, TargetInfo
from benchmark_platform.utils.challenge import ChallengeManager


def _make_challenge(code: str, level: int, solved: bool = False) -> Challenge:
    level_map = {1: Difficulty.EASY, 2: Difficulty.MEDIUM, 3: Difficulty.HARD}
    c = Challenge(
        challenge_code=code,
        difficulty=level_map[level],
        points={1: 200, 2: 300, 3: 500}[level],
        hint_viewed=False,
        solved=solved,
        target_info=TargetInfo(ip="localhost", port=[8080]),
    )
    c.set_benchmark_id(f"XBEN-{code}")
    return c


def _make_manager(challenges: list[Challenge], no_level_gate: bool = False) -> ChallengeManager:
    mgr = ChallengeManager(
        benchmark_folders=[],
        benchmark_ids=[],
        public_accessible_host="localhost",
        no_level_gate=no_level_gate,
    )
    mgr.challenges = challenges
    return mgr


def test_current_level_all_unsolved():
    mgr = _make_manager([
        _make_challenge("001", 1),
        _make_challenge("002", 2),
    ])
    assert mgr.get_current_level() == 1


def test_current_level_after_solving_level1():
    mgr = _make_manager([
        _make_challenge("001", 1, solved=True),
        _make_challenge("002", 1, solved=True),
        _make_challenge("003", 2),
    ])
    assert mgr.get_current_level() == 2


def test_current_level_all_solved():
    mgr = _make_manager([
        _make_challenge("001", 1, solved=True),
        _make_challenge("002", 2, solved=True),
    ])
    assert mgr.get_current_level() == 2


def test_is_level_unlocked():
    mgr = _make_manager([
        _make_challenge("001", 1, solved=True),
        _make_challenge("002", 1, solved=True),
        _make_challenge("003", 2),
        _make_challenge("004", 3),
    ])
    assert mgr.is_level_unlocked(1) is True
    assert mgr.is_level_unlocked(2) is True
    assert mgr.is_level_unlocked(3) is False


def test_no_level_gate_unlocks_all():
    mgr = _make_manager(
        [_make_challenge("001", 1), _make_challenge("002", 3)],
        no_level_gate=True,
    )
    assert mgr.is_level_unlocked(1) is True
    assert mgr.is_level_unlocked(3) is True


def test_get_level_for_challenge():
    mgr = _make_manager([])
    c = _make_challenge("001", 2)
    assert mgr.get_level_for_challenge(c) == 2


def test_no_challenges():
    mgr = _make_manager([])
    assert mgr.get_current_level() == 1
    assert mgr.is_level_unlocked(1) is True
