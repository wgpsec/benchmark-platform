"""Build template context dicts from ChallengeManager and SubmissionStore state."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from benchmark_platform.utils.challenge import ChallengeManager
    from benchmark_platform.web.submission_store import SubmissionStore


def _challenge_to_card(manager: ChallengeManager, challenge) -> dict:
    bm = challenge.get_benchmark()
    status = manager.get_instance_status(challenge.challenge_code)
    entrypoint = None
    if status == "running":
        entrypoint = [
            f"{manager.public_accessible_host}:{p}" for p in challenge.target_info.port
        ]
    return {
        "challenge_code": challenge.challenge_code,
        "benchmark_id": challenge.get_benchmark_id(),
        "name": bm.name,
        "description": bm.description,
        "level": bm.level,
        "difficulty": challenge.difficulty.value,
        "points": challenge.points,
        "flag_count": challenge.flag_count,
        "solved_count": challenge.solved_count,
        "solved": challenge.solved,
        "hint_viewed": challenge.hint_viewed,
        "instance_status": status,
        "entrypoint": entrypoint,
        "emulated": challenge.emulated,
        "flag_states": [
            {"id": fs.id, "route": fs.route, "description": fs.description, "solved": fs.solved}
            for fs in challenge.flag_states
        ],
    }


def leaderboard_context() -> list:
    """Get team leaderboard data for dashboard."""
    from benchmark_platform.db import list_teams
    return list_teams()


def dashboard_context(manager: ChallengeManager, store: SubmissionStore) -> dict:
    challenges = manager.challenges
    total_challenges = len(challenges)
    solved_challenges = sum(1 for c in challenges if c.solved)
    total_flags = sum(c.flag_count for c in challenges)
    solved_flags = sum(c.solved_count for c in challenges)
    total_points = sum(c.points for c in challenges)
    earned_points = sum(c.points for c in challenges if c.solved)
    running_count = sum(
        1 for c in challenges if manager.get_instance_status(c.challenge_code) in ("running", "unhealthy")
    )

    levels_seen: dict[int, dict] = {}
    for c in challenges:
        lv = manager.get_level_for_challenge(c)
        if lv not in levels_seen:
            levels_seen[lv] = {"level": lv, "total": 0, "solved": 0, "unlocked": False}
        levels_seen[lv]["total"] += 1
        if c.solved:
            levels_seen[lv]["solved"] += 1
    for lv_data in levels_seen.values():
        lv_data["unlocked"] = manager.is_level_unlocked(lv_data["level"])
    level_progress = sorted(levels_seen.values(), key=lambda x: x["level"])

    diff_map: dict[str, dict] = {}
    for c in challenges:
        d = c.difficulty.value
        if d not in diff_map:
            diff_map[d] = {"difficulty": d, "total": 0, "solved": 0}
        diff_map[d]["total"] += 1
        if c.solved:
            diff_map[d]["solved"] += 1
    order = ["easy", "medium", "hard"]
    difficulty_stats = [diff_map[d] for d in order if d in diff_map]

    recent = store.query(limit=10)

    leaderboard = leaderboard_context()

    return {
        "total_challenges": total_challenges,
        "solved_challenges": solved_challenges,
        "total_flags": total_flags,
        "solved_flags": solved_flags,
        "total_points": total_points,
        "earned_points": earned_points,
        "running_count": running_count,
        "level_progress": level_progress,
        "difficulty_stats": difficulty_stats,
        "recent_submissions": recent,
        "submission_total": store.total_count,
        "submission_correct": store.correct_count,
        "submission_incorrect": store.incorrect_count,
        "leaderboard": leaderboard,
    }


def challenges_context(manager: ChallengeManager) -> dict:
    groups: dict[int, list[dict]] = {}
    for c in manager.challenges:
        lv = manager.get_level_for_challenge(c)
        if lv not in groups:
            groups[lv] = []
        groups[lv].append(_challenge_to_card(manager, c))

    level_groups = []
    for lv in sorted(groups.keys()):
        total = len(groups[lv])
        solved = sum(1 for card in groups[lv] if card["solved"])
        level_groups.append({
            "level": lv,
            "challenges": groups[lv],
            "total": total,
            "solved": solved,
            "all_solved": solved == total,
            "unlocked": manager.is_level_unlocked(lv),
        })

    return {
        "level_groups": level_groups,
        "total_challenges": len(manager.challenges),
        "total_flags": sum(c.flag_count for c in manager.challenges),
    }


def status_context(manager: ChallengeManager) -> dict:
    running = []
    stopped = []
    for c in manager.challenges:
        card = _challenge_to_card(manager, c)
        if card["instance_status"] in ("running", "unhealthy"):
            running.append(card)
        else:
            stopped.append(card)
    return {
        "running": running,
        "stopped": stopped,
        "running_count": len(running),
        "stopped_count": len(stopped),
        "total": len(running) + len(stopped),
    }


def history_context(store: SubmissionStore, correct: bool | None = None, limit: int = 50, offset: int = 0) -> dict:
    records = store.query(correct=correct, limit=limit, offset=offset)
    return {
        "records": records,
        "total": store.total_count,
        "correct_count": store.correct_count,
        "incorrect_count": store.incorrect_count,
        "filter_correct": correct,
        "limit": limit,
        "offset": offset,
    }
