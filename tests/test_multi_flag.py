"""Tests for multi-flag challenge support."""
from benchmark_platform.base import Challenge, FlagState, TargetInfo, Difficulty


def test_multi_flag_count():
    c = Challenge(
        challenge_code="test-multi",
        difficulty=Difficulty.MEDIUM,
        points=300,
        hint_viewed=False,
        solved=False,
        target_info=TargetInfo(ip="localhost", port=[8080]),
        flag_states=[
            FlagState(id="flag1", route="/route1", description="variant 1"),
            FlagState(id="flag2", route="/route2", description="variant 2"),
            FlagState(id="flag3", route="/route3", description="variant 3"),
        ],
    )
    assert c.flag_count == 3
    assert c.solved_count == 0


def test_partial_solve():
    c = Challenge(
        challenge_code="test-multi",
        difficulty=Difficulty.MEDIUM,
        points=300,
        hint_viewed=False,
        solved=False,
        target_info=TargetInfo(ip="localhost", port=[8080]),
        flag_states=[
            FlagState(id="flag1", route="/route1", description="variant 1"),
            FlagState(id="flag2", route="/route2", description="variant 2"),
            FlagState(id="flag3", route="/route3", description="variant 3"),
        ],
    )
    c.flag_states[0].solved = True
    assert c.solved_count == 1
    assert not c.solved


def test_full_solve():
    c = Challenge(
        challenge_code="test-multi",
        difficulty=Difficulty.MEDIUM,
        points=300,
        hint_viewed=False,
        solved=False,
        target_info=TargetInfo(ip="localhost", port=[8080]),
        flag_states=[
            FlagState(id="flag1", route="/route1", description="variant 1"),
            FlagState(id="flag2", route="/route2", description="variant 2"),
        ],
    )
    for fs in c.flag_states:
        fs.solved = True
    assert c.solved_count == 2
    assert c.flag_count == 2


def test_single_flag_compat():
    c = Challenge(
        challenge_code="test-single",
        difficulty=Difficulty.EASY,
        points=200,
        hint_viewed=False,
        solved=False,
        target_info=TargetInfo(ip="localhost", port=[8080]),
    )
    assert c.flag_count == 1
    assert c.solved_count == 0
    c.solved = True
    assert c.solved_count == 1


def test_flag_state_defaults():
    fs = FlagState(id="test")
    assert fs.route == "/"
    assert fs.description == ""
    assert fs.solved is False
    assert fs.solved_at is None
