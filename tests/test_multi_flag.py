"""Tests for multi-flag challenge support."""
import json

from benchmark_platform.base import Challenge, FlagState, TargetInfo, Difficulty
from benchmark_platform.utils.challenge import ChallengeManager


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


def test_dynamic_flag_replacement_scans_c_sources(tmp_path):
    challenge_dir = tmp_path / "challenges" / "custom" / "C-001"
    challenge_dir.mkdir(parents=True)
    (challenge_dir / "benchmark.json").write_text(json.dumps({
        "id": "C-001",
        "name": "C source challenge",
        "description": "test",
        "hint": "test",
        "level": 1,
        "win_condition": "flag",
        "tags": ["c"],
        "canaries": ["FLAG{from_c_source}"],
    }))
    (challenge_dir / ".env").write_text('FLAG="FLAG{from_c_source}"\n')
    (challenge_dir / "docker-compose.yml").write_text("services: {}\n")
    (challenge_dir / "main.c").write_text('char flag[] = "FLAG{from_c_source}";\n')

    runtime_dir = tmp_path / "runtime"
    manager = ChallengeManager(
        benchmark_folders=[tmp_path / "challenges" / "custom"],
        benchmark_ids=["C-001"],
        public_accessible_host="127.0.0.1",
        no_level_gate=True,
        runtime_dir=runtime_dir,
    ).start()

    challenge = manager.challenges[0]
    runtime_challenge = runtime_dir / "C-001" / challenge.challenge_code
    rewritten = (runtime_challenge / "main.c").read_text()
    answers = challenge.get_expected_answers()

    assert "FLAG{from_c_source}" not in rewritten
    assert answers["default"] in rewritten
