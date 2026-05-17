"""Static checks for imported StratoCyberLab challenges."""
from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CUSTOM = ROOT / "challenges" / "custom"


def _load_challenge(challenge_id: str) -> tuple[Path, dict, dict, dict]:
    path = CUSTOM / challenge_id
    meta = json.loads((path / "benchmark.json").read_text(encoding="utf-8"))
    flags = yaml.safe_load((path / "benchmark.yaml").read_text(encoding="utf-8"))
    compose = yaml.safe_load((path / "docker-compose.yml").read_text(encoding="utf-8"))
    return path, meta, flags, compose


def test_jump_around_is_platform_native() -> None:
    _, meta, flags, compose = _load_challenge("JUMP-AROUND-001")

    assert meta["flag_count"] == 2
    assert len(meta["canaries"]) == 2
    assert len(flags["flags"]) == 2
    assert "ports" in compose["services"]["proxy-hop"]
    assert "container_name" not in str(compose)
    assert "playground-net" not in str(compose)
    assert "ipv4_address" not in str(compose)


def test_corporate_retreat_keeps_multinet_shape_without_external_network() -> None:
    _, meta, flags, compose = _load_challenge("MIRO-CORP-RETREAT-001")

    assert meta["flag_count"] == 6
    assert len(meta["canaries"]) == 6
    assert len(flags["flags"]) == 6
    assert "ports" in compose["services"]["camera"]
    assert "container_name" not in str(compose)
    assert "playground-net" not in str(compose)
    assert "external" not in str(compose.get("networks", {}))
    assert {"cr-public", "cr-aux", "cr-cn1", "cr-dc1"} <= set(compose["networks"])
