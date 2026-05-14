"""Tests for web context builder functions."""
from unittest.mock import patch

from benchmark_platform.base import Challenge, Difficulty, FlagState, TargetInfo
from benchmark_platform.models.benchmark import Benchmark, WinCondition
from benchmark_platform.web.context import dashboard_context, challenges_context
from benchmark_platform.web.submission_store import SubmissionRecord, SubmissionStore
from benchmark_platform.utils.challenge import ChallengeManager


def _fake_get_benchmark(self) -> Benchmark:
    level_map = {Difficulty.EASY: 1, Difficulty.MEDIUM: 2, Difficulty.HARD: 3}
    return Benchmark(
        id=self.get_benchmark_id(),
        name=f"Challenge {self.challenge_code}",
        description=f"Desc for {self.challenge_code}",
        level=level_map[self.difficulty],
        win_condition=WinCondition.FLAG,
        tags=["test"],
        canaries=[],
    )


def _make_challenge(code: str, level: int, solved: bool = False, flag_count: int = 1) -> Challenge:
    level_map = {1: Difficulty.EASY, 2: Difficulty.MEDIUM, 3: Difficulty.HARD}
    flags = []
    if flag_count > 1:
        flags = [FlagState(id=f"f{i}", route=f"/r{i}", description=f"flag {i}") for i in range(flag_count)]
    c = Challenge(
        challenge_code=code,
        difficulty=level_map[level],
        points={1: 200, 2: 300, 3: 500}[level],
        hint_viewed=False,
        solved=solved,
        target_info=TargetInfo(ip="localhost", port=[8080]),
        flag_states=flags,
    )
    c.set_benchmark_id(f"XBEN-{code}")
    return c


def _make_manager(challenges: list[Challenge]) -> ChallengeManager:
    mgr = ChallengeManager(
        benchmark_folders=[],
        benchmark_ids=[],
        public_accessible_host="localhost",
    )
    mgr.challenges = challenges
    for c in challenges:
        mgr._instance_status[c.challenge_code] = "stopped"
    return mgr


def test_dashboard_context_basic():
    mgr = _make_manager([
        _make_challenge("001", 1, solved=True),
        _make_challenge("002", 1, solved=False),
        _make_challenge("003", 2, solved=False),
    ])
    store = SubmissionStore()
    with patch.object(Challenge, 'get_benchmark', _fake_get_benchmark):
        ctx = dashboard_context(mgr, store)
    assert ctx["total_challenges"] == 3
    assert ctx["solved_challenges"] == 1
    assert ctx["total_flags"] == 3
    assert ctx["total_points"] == 200 + 200 + 300
    assert ctx["earned_points"] == 200


def test_dashboard_context_difficulty_stats():
    mgr = _make_manager([
        _make_challenge("001", 1, solved=True),
        _make_challenge("002", 1, solved=False),
        _make_challenge("003", 2, solved=True),
    ])
    store = SubmissionStore()
    with patch.object(Challenge, 'get_benchmark', _fake_get_benchmark):
        ctx = dashboard_context(mgr, store)
    diff = {d["difficulty"]: d for d in ctx["difficulty_stats"]}
    assert diff["easy"]["total"] == 2
    assert diff["easy"]["solved"] == 1
    assert diff["medium"]["total"] == 1
    assert diff["medium"]["solved"] == 1


def test_dashboard_context_level_progress():
    mgr = _make_manager([
        _make_challenge("001", 1, solved=True),
        _make_challenge("002", 1, solved=True),
        _make_challenge("003", 2, solved=False),
    ])
    store = SubmissionStore()
    with patch.object(Challenge, 'get_benchmark', _fake_get_benchmark):
        ctx = dashboard_context(mgr, store)
    levels = {lp["level"]: lp for lp in ctx["level_progress"]}
    assert levels[1]["solved"] == 2
    assert levels[1]["total"] == 2
    assert levels[1]["unlocked"] is True
    assert levels[2]["unlocked"] is True
    assert levels[2]["solved"] == 0


def test_challenges_context_groups_by_level():
    mgr = _make_manager([
        _make_challenge("001", 1),
        _make_challenge("002", 2),
        _make_challenge("003", 1),
    ])
    with patch.object(Challenge, 'get_benchmark', _fake_get_benchmark):
        ctx = challenges_context(mgr)
    assert len(ctx["level_groups"]) == 2
    assert ctx["level_groups"][0]["level"] == 1
    assert len(ctx["level_groups"][0]["challenges"]) == 2
    assert ctx["level_groups"][1]["level"] == 2


def test_challenges_context_includes_status():
    mgr = _make_manager([_make_challenge("001", 1)])
    mgr._instance_status["001"] = "running"
    with patch.object(Challenge, 'get_benchmark', _fake_get_benchmark):
        ctx = challenges_context(mgr)
    card = ctx["level_groups"][0]["challenges"][0]
    assert card["instance_status"] == "running"


def test_challenge_to_card_unsupported():
    """Unsupported challenge should have unsupported=True in card context."""
    c = Challenge(
        challenge_code="ad001",
        difficulty=Difficulty.MEDIUM,
        points=300,
        hint_viewed=False,
        solved=False,
        target_info=TargetInfo(ip="localhost", port=[8080]),
        unsupported=True,
        unsupported_reason="需要 x86_64 架构 + KVM 虚拟化",
    )
    c.set_benchmark_id("AD-001")

    mgr = _make_manager([c])

    with patch.object(Challenge, 'get_benchmark', _fake_get_benchmark):
        with patch('benchmark_platform.db.is_challenge_enabled', return_value=True):
            from benchmark_platform.web.context import _challenge_to_card
            card = _challenge_to_card(mgr, c)

    assert card["unsupported"] is True
    assert card["unsupported_reason"] == "需要 x86_64 架构 + KVM 虚拟化"


def test_challenge_to_card_supported():
    """Normal challenge should have unsupported=False."""
    c = _make_challenge("001", 1)
    mgr = _make_manager([c])

    with patch.object(Challenge, 'get_benchmark', _fake_get_benchmark):
        with patch('benchmark_platform.db.is_challenge_enabled', return_value=True):
            from benchmark_platform.web.context import _challenge_to_card
            card = _challenge_to_card(mgr, c)

    assert card["unsupported"] is False
    assert card["unsupported_reason"] == ""


def test_challenge_to_card_requires_windows_iso():
    """Challenge with requires_windows_iso=True should expose it in card dict."""
    c = Challenge(
        challenge_code="ad001",
        difficulty=Difficulty.MEDIUM,
        points=300,
        hint_viewed=False,
        solved=False,
        target_info=TargetInfo(ip="localhost", port=[8080]),
        requires_windows_iso=True,
    )
    c.set_benchmark_id("AD-001")
    mgr = _make_manager([c])

    with patch.object(Challenge, 'get_benchmark', _fake_get_benchmark):
        with patch('benchmark_platform.db.is_challenge_enabled', return_value=True):
            from benchmark_platform.web.context import _challenge_to_card
            card = _challenge_to_card(mgr, c)

    assert card["requires_windows_iso"] is True


def test_challenge_to_card_no_windows_iso():
    """Normal challenge should have requires_windows_iso=False."""
    c = _make_challenge("001", 1)
    mgr = _make_manager([c])

    with patch.object(Challenge, 'get_benchmark', _fake_get_benchmark):
        with patch('benchmark_platform.db.is_challenge_enabled', return_value=True):
            from benchmark_platform.web.context import _challenge_to_card
            card = _challenge_to_card(mgr, c)

    assert card["requires_windows_iso"] is False
