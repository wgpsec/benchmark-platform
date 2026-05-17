"""MCP Server — exposes challenge platform tools via Streamable HTTP at /mcp."""
from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP, Context
from fastmcp.server.dependencies import get_http_request

from benchmark_platform.db import (
    get_team_by_token,
    get_or_create_default_team,
    get_team_solved_count,
    is_hint_viewed,
    mark_flag_solved,
    mark_hint_viewed,
    get_team_progress,
    is_challenge_enabled,
)

mcp = FastMCP(
    name="benchmark-platform",
    instructions="CTF challenge platform MCP server. Use tools to list challenges, start/stop instances, submit flags, and view hints.",
)

# Set by server.py after initialization — avoids circular import of server module
_manager_ref = None


def set_manager(mgr):
    """Called by server.py to inject the ChallengeManager reference."""
    global _manager_ref
    _manager_ref = mgr


def _get_team_from_request() -> dict:
    """Extract team from Authorization header of the current HTTP request."""
    request = get_http_request()
    auth = request.headers.get("authorization", "")
    token = None
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    elif auth:
        token = auth.strip()

    if not token:
        agent_token = request.headers.get("agent-token", "")
        if agent_token:
            token = agent_token

    if not token:
        raise ValueError("Missing authentication token. Provide Authorization: Bearer <token> header.")

    team = get_team_by_token(token)
    if team is None:
        raise ValueError("Invalid token or team disabled")
    return team


def _get_manager():
    """Get the ChallengeManager reference."""
    if _manager_ref is None:
        raise ValueError("Server not initialized")
    return _manager_ref


@mcp.tool()
def list_challenges() -> str:
    """获取当前关卡及之前关卡的赛题列表，包含队伍得分情况和实例状态。"""
    team = _get_team_from_request()
    mgr = _get_manager()

    all_challenges = [
        c for c in mgr.challenges
        if is_challenge_enabled(c.get_benchmark_id())
    ]
    team_prog = get_team_progress(team["id"])
    challenge_list = []
    total_solved = 0

    for c in all_challenges:
        bm = c.get_benchmark()
        bm_id = c.get_benchmark_id()
        status = mgr.get_instance_status(c.challenge_code)
        entrypoint = None
        if status in ("running", "unhealthy"):
            entrypoint = [f"{mgr.public_accessible_host}:{p}" for p in c.target_info.port]

        team_solved = get_team_solved_count(team["id"], bm_id)
        all_solved = team_solved >= c.flag_count
        hint_viewed = is_hint_viewed(team["id"], bm_id)

        if all_solved:
            total_solved += 1

        if c.flag_count > 0:
            per_flag_score = c.points // c.flag_count
            got_score = per_flag_score * team_solved
        else:
            got_score = c.points if all_solved else 0

        challenge_list.append({
            "title": bm.name,
            "code": c.challenge_code,
            "difficulty": c.difficulty.value,
            "description": bm.description,
            "level": bm.level,
            "total_score": c.points,
            "total_got_score": got_score,
            "flag_count": c.flag_count,
            "flag_got_count": team_solved,
            "hint_viewed": hint_viewed,
            "instance_status": status,
            "entrypoint": entrypoint,
            "unsupported": c.unsupported,
            "unsupported_reason": c.unsupported_reason,
        })

    return json.dumps({
        "current_level": mgr.get_current_level(team["id"]),
        "total_challenges": len(all_challenges),
        "solved_challenges": total_solved,
        "challenges": challenge_list,
    }, ensure_ascii=False)


def _ensure_enabled(challenge) -> None:
    if not is_challenge_enabled(challenge.get_benchmark_id()):
        raise ValueError("该题目已被管理员关闭")


@mcp.tool()
def start_challenge(code: str) -> str:
    """启动指定赛题的容器实例。每队最多同时运行3个实例，超出需先停止其他实例。

    Args:
        code: 赛题唯一标识
    """
    team = _get_team_from_request()
    mgr = _get_manager()

    try:
        challenge = mgr._find_by_code(code)
    except KeyError:
        raise ValueError(f"赛题 {code} 不存在")

    _ensure_enabled(challenge)

    if challenge.unsupported:
        return json.dumps({"message": f"该赛题不支持当前平台: {challenge.unsupported_reason}", "unsupported": True}, ensure_ascii=False)

    challenge_level = mgr.get_level_for_challenge(challenge)
    if not mgr.is_level_unlocked(challenge_level, team["id"]):
        raise ValueError(f"尚未解锁关卡 {challenge_level}，请先通过前置关卡")

    team_solved = get_team_solved_count(team["id"], challenge.get_benchmark_id())
    if team_solved >= challenge.flag_count:
        return json.dumps({"message": "该赛题已全部完成，无需再启动实例", "already_completed": True}, ensure_ascii=False)

    if mgr.get_instance_status(code) in ("running", "unhealthy"):
        entrypoints = [f"{mgr.public_accessible_host}:{p}" for p in challenge.target_info.port]
        started_at, expires_at = mgr.get_instance_timestamps(code)
        return json.dumps({"message": "赛题实例已在运行中", "entrypoint": entrypoints,
                           "started_at": started_at, "expires_at": expires_at}, ensure_ascii=False)

    try:
        entrypoints = mgr.start_challenge_instance(code)
    except Exception as e:
        raise ValueError(f"赛题启动失败: {e}")

    started_at, expires_at = mgr.get_instance_timestamps(challenge.challenge_code)
    return json.dumps({"message": "赛题实例启动成功", "entrypoint": entrypoints,
                       "started_at": started_at, "expires_at": expires_at}, ensure_ascii=False)


@mcp.tool()
def stop_challenge(code: str) -> str:
    """停止指定赛题的已启动容器实例。

    Args:
        code: 赛题唯一标识
    """
    team = _get_team_from_request()
    mgr = _get_manager()

    try:
        challenge = mgr._find_by_code(code)
    except KeyError:
        raise ValueError(f"赛题 {code} 不存在")

    _ensure_enabled(challenge)

    if mgr.get_instance_status(code) not in ("running", "unhealthy"):
        raise ValueError("赛题实例未运行")

    try:
        mgr.stop_challenge_instance(code)
    except Exception as e:
        raise ValueError(f"停止失败: {e}")

    return json.dumps({"message": "赛题实例已停止"}, ensure_ascii=False)


@mcp.tool()
def submit_flag(code: str, flag: str) -> str:
    """提交赛题的 Flag 答案。需要赛题实例处于运行状态。

    Args:
        code: 赛题唯一标识
        flag: 提交的 Flag 值，格式通常为 flag{...}
    """
    team = _get_team_from_request()
    mgr = _get_manager()

    try:
        challenge = mgr._find_by_code(code)
    except KeyError:
        raise ValueError(f"赛题 {code} 不存在")

    _ensure_enabled(challenge)

    challenge_level = mgr.get_level_for_challenge(challenge)
    if not mgr.is_level_unlocked(challenge_level, team["id"]):
        raise ValueError(f"尚未解锁关卡 {challenge_level}，请先通过前置关卡")

    if mgr.get_instance_status(code) not in ("running", "unhealthy"):
        raise ValueError("赛题实例未运行")

    try:
        answers = challenge.get_expected_answers()
    except Exception as e:
        raise ValueError(f"获取预期答案失败: {e}")

    matched_flag_id = None
    for fid, fval in answers.items():
        if fval == flag:
            matched_flag_id = fid
            break

    is_correct = matched_flag_id is not None

    if is_correct:
        mark_flag_solved(team["id"], challenge.get_benchmark_id(), matched_flag_id)
        for fs in challenge.flag_states:
            if fs.id == matched_flag_id:
                fs.solved = True
                break

    team_solved = get_team_solved_count(team["id"], challenge.get_benchmark_id())
    all_solved = team_solved >= challenge.flag_count
    if all_solved:
        challenge.solved = True

    if is_correct:
        per_flag_score = challenge.points // challenge.flag_count if challenge.flag_count > 0 else challenge.points
        msg = f"恭喜！答案正确（{team_solved}/{challenge.flag_count}），获得{per_flag_score}分"
    else:
        msg = "答案错误，请继续尝试"

    return json.dumps({
        "correct": is_correct,
        "message": msg,
        "flag_count": challenge.flag_count,
        "flag_got_count": team_solved,
    }, ensure_ascii=False)


@mcp.tool()
def view_hint(code: str) -> str:
    """查看指定赛题的提示信息。首次查看会扣除该题总分的10%。

    Args:
        code: 赛题唯一标识
    """
    team = _get_team_from_request()
    mgr = _get_manager()

    try:
        challenge = mgr._find_by_code(code)
    except KeyError:
        raise ValueError(f"赛题 {code} 不存在")

    _ensure_enabled(challenge)

    if mgr.get_instance_status(code) not in ("running", "unhealthy"):
        raise ValueError("请先启动赛题实例")

    team_solved = get_team_solved_count(team["id"], challenge.get_benchmark_id())
    if team_solved >= challenge.flag_count:
        raise ValueError("该赛题已全部答对，无法查看提示")

    try:
        hint = challenge.get_hint()
    except Exception as e:
        raise ValueError(f"获取提示失败: {e}")

    mark_hint_viewed(team["id"], challenge.get_benchmark_id())
    return json.dumps({"code": code, "hint_content": hint}, ensure_ascii=False)
