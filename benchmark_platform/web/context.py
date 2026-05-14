"""Build template context dicts from ChallengeManager and SubmissionStore state."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from benchmark_platform.utils.challenge import ChallengeManager
    from benchmark_platform.web.submission_store import SubmissionStore


def _get_team_progress_for_view(team_id: Optional[str]) -> dict:
    if not team_id:
        return {}
    from benchmark_platform.db import get_team_progress
    return get_team_progress(team_id)


def _challenge_to_card(manager: ChallengeManager, challenge, team_id: Optional[str] = None, team_progress: Optional[dict] = None) -> dict:
    bm = challenge.get_benchmark()
    status = manager.get_instance_status(challenge.challenge_code)
    entrypoint = None
    if status == "running":
        entrypoint = [
            f"{manager.public_accessible_host}:{p}" for p in challenge.target_info.port
        ]

    bm_id = challenge.get_benchmark_id()
    from benchmark_platform.db import is_challenge_enabled
    enabled = is_challenge_enabled(bm_id)

    if team_id:
        if team_progress is None:
            team_progress = _get_team_progress_for_view(team_id)
        progress = team_progress.get(bm_id, {})
        solved_count = len(progress)
        all_solved = solved_count >= challenge.flag_count
        from benchmark_platform.db import is_hint_viewed
        hint_viewed = is_hint_viewed(team_id, bm_id)
        flag_states = [
            {"id": fs.id, "route": fs.route, "description": fs.description, "solved": progress.get(fs.id, False)}
            for fs in challenge.flag_states
        ]
    else:
        solved_count = challenge.solved_count
        all_solved = challenge.solved
        hint_viewed = challenge.hint_viewed
        flag_states = [
            {"id": fs.id, "route": fs.route, "description": fs.description, "solved": fs.solved}
            for fs in challenge.flag_states
        ]

    started_at, expires_at = None, None
    if manager.get_instance_status(challenge.challenge_code) in ("running", "unhealthy"):
        started_at, expires_at = manager.get_instance_timestamps(challenge.challenge_code)

    return {
        "challenge_code": challenge.challenge_code,
        "benchmark_id": bm_id,
        "name": bm.name,
        "description": bm.description,
        "level": bm.level,
        "difficulty": challenge.difficulty.value,
        "points": challenge.points,
        "flag_count": challenge.flag_count,
        "solved_count": solved_count,
        "solved": all_solved,
        "hint_viewed": hint_viewed,
        "instance_status": status,
        "entrypoint": entrypoint,
        "emulated": challenge.emulated,
        "unsupported": challenge.unsupported,
        "unsupported_reason": challenge.unsupported_reason,
        "flag_states": flag_states,
        "enabled": enabled,
        "started_at": started_at,
        "expires_at": expires_at,
    }


def leaderboard_context() -> list:
    """Get team leaderboard data for dashboard."""
    from benchmark_platform.db import list_teams
    return list_teams()


def dashboard_context(manager: ChallengeManager, store: SubmissionStore, team_id: Optional[str] = None) -> dict:
    challenges = manager.challenges

    if team_id:
        team_progress = _get_team_progress_for_view(team_id)

        total_challenges = len(challenges)
        solved_challenges = 0
        total_flags = sum(c.flag_count for c in challenges)
        solved_flags = 0
        total_points = sum(c.points for c in challenges)
        earned_points = 0

        for c in challenges:
            bm_id = c.get_benchmark_id()
            progress = team_progress.get(bm_id, {})
            sc = len(progress)
            solved_flags += sc
            if sc >= c.flag_count:
                solved_challenges += 1
                earned_points += c.points
    else:
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
        if team_id:
            bm_id = c.get_benchmark_id()
            sc = len(team_progress.get(bm_id, {}))
            if sc >= c.flag_count:
                levels_seen[lv]["solved"] += 1
        else:
            if c.solved:
                levels_seen[lv]["solved"] += 1
    for lv_data in levels_seen.values():
        lv_data["unlocked"] = manager.is_level_unlocked(lv_data["level"], team_id)
    level_progress = sorted(levels_seen.values(), key=lambda x: x["level"])

    diff_map: dict[str, dict] = {}
    for c in challenges:
        d = c.difficulty.value
        if d not in diff_map:
            diff_map[d] = {"difficulty": d, "total": 0, "solved": 0}
        diff_map[d]["total"] += 1
        if team_id:
            bm_id = c.get_benchmark_id()
            sc = len(team_progress.get(bm_id, {}))
            if sc >= c.flag_count:
                diff_map[d]["solved"] += 1
        else:
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


def challenges_context(manager: ChallengeManager, team_id: Optional[str] = None) -> dict:
    team_progress = _get_team_progress_for_view(team_id) if team_id else None
    groups: dict[int, list[dict]] = {}
    for c in manager.challenges:
        lv = manager.get_level_for_challenge(c)
        if lv not in groups:
            groups[lv] = []
        groups[lv].append(_challenge_to_card(manager, c, team_id=team_id, team_progress=team_progress))

    level_groups = []
    for lv in sorted(groups.keys()):
        total = len(groups[lv])
        solved = sum(1 for card in groups[lv] if card["solved"])
        enabled_count = sum(1 for card in groups[lv] if card["enabled"])
        level_groups.append({
            "level": lv,
            "challenges": groups[lv],
            "total": total,
            "solved": solved,
            "all_solved": solved == total,
            "unlocked": manager.is_level_unlocked(lv, team_id),
            "enabled_count": enabled_count,
            "all_enabled": enabled_count == total,
            "all_disabled": enabled_count == 0,
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
