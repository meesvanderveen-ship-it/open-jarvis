#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.atomic_io import atomic_write_json
from bot.autonomous_parameter_governor import ENV_ALLOWLIST


DEFAULT_VALUES = {
    "ENABLE_AUTONOMOUS_PARAMETER_GOVERNOR": "true",
    "AUTONOMOUS_PARAMETER_GOVERNOR_MODE": "apply_when_safe",
    "AUTONOMOUS_PARAMETER_GOVERNOR_ACK": "I_APPROVE_AUTONOMOUS_PARAMETER_GOVERNOR_BOUNDED_PROFILE_ACTIVATION",
    "AUTONOMOUS_PARAMETER_GOVERNOR_REQUIRED_ACK": "I_APPROVE_AUTONOMOUS_PARAMETER_GOVERNOR_BOUNDED_PROFILE_ACTIVATION",
    "ADAPTIVE_MIN_MARKET_REGIMES_FOR_ANALYSIS": "2",
    "ADAPTIVE_MIN_MARKET_REGIMES_FOR_PREPARE": "2",
    "ADAPTIVE_MIN_MARKET_REGIMES_FOR_APPLY": "3",
    "ADAPTIVE_MIN_REGIME_ENRICHMENT_COVERAGE_PCT": "85",
    "ADAPTIVE_REQUIRE_DIRECTION_STABILITY_RUNS": "3",
    "ADAPTIVE_MIN_EFFECT_SIZE_PCT": "5",
    "ADAPTIVE_CONFIDENCE_BUFFER_PCT": "3",
    "ADAPTIVE_SHRINKAGE_FACTOR": "0.50",
    "AUTONOMOUS_PARAMETER_MAX_CHANGES_PER_24H": "1",
    "AUTONOMOUS_PARAMETER_MAX_PARAMETERS_PER_ACTIVATION": "1",
    "AUTONOMOUS_PARAMETER_COOLDOWN_HOURS": "24",
    "AUTONOMOUS_PARAMETER_APPLY_ONLY_WHEN_NO_OPEN_ORDERS": "true",
    "AUTONOMOUS_PARAMETER_APPLY_ONLY_WHEN_NO_OPEN_POSITIONS": "true",
    "AUTONOMOUS_PARAMETER_REQUIRE_BACKUP": "true",
    "AUTONOMOUS_PARAMETER_REQUIRE_ROLLBACK_PLAN": "true",
    "AUTONOMOUS_PARAMETER_WRITE_AUDIT_TRAIL": "true",
}


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_env_lines(text: str) -> tuple[list[str], Dict[str, str]]:
    lines = text.splitlines()
    values: Dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value
    return lines, values


def render_updated_env(lines: list[str], updates: Dict[str, str]) -> str:
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        if "=" not in line or line.strip().startswith("#"):
            out.append(line)
            continue
        key, _value = line.split("=", 1)
        clean = key.strip()
        if clean in remaining:
            out.append(f"{clean}={remaining.pop(clean)}")
        else:
            out.append(line)
    if remaining:
        if out and out[-1].strip():
            out.append("")
        out.extend(f"{key}={remaining[key]}" for key in sorted(remaining))
    return "\n".join(out) + "\n"


def configure_env(*, root: Path, apply: bool) -> Dict[str, object]:
    forbidden = sorted(set(DEFAULT_VALUES) - set(ENV_ALLOWLIST))
    if forbidden:
        raise ValueError(f"internal forbidden env keys: {forbidden}")
    env_path = root / ".env"
    before = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines, current = parse_env_lines(before)
    changed = {key: value for key, value in DEFAULT_VALUES.items() if current.get(key) != value}
    backup_path = root / "backups" / f".env.before_autonomous_parameter_governor_{now_stamp()}"
    profile_path = root / "state/approved_parameter_profile.json"
    profile_backup_path = root / "backups" / f"approved_parameter_profile.before_autonomous_parameter_governor_env_{now_stamp()}.json"
    audit = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "applied": False,
        "env_path": str(env_path),
        "backup_path": str(backup_path),
        "approved_profile_backup_path": str(profile_backup_path),
        "allowlist": sorted(ENV_ALLOWLIST),
        "changed_keys": sorted(changed),
        "forbidden_keys_changed": [],
    }
    if apply:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        if env_path.exists():
            shutil.copy2(env_path, backup_path)
        else:
            backup_path.write_text("", encoding="utf-8")
        if profile_path.exists():
            shutil.copy2(profile_path, profile_backup_path)
        else:
            profile_backup_path.write_text("{}", encoding="utf-8")
        env_path.write_text(render_updated_env(lines, DEFAULT_VALUES), encoding="utf-8")
        audit["applied"] = True
    atomic_write_json(root / "reports/autonomous_parameter_governor/env-config-latest.json", audit)
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configure allowlisted autonomous parameter governor .env keys.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = configure_env(root=Path(args.root), apply=args.apply)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"applied={result['applied']} changed_keys={len(result['changed_keys'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
