#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.approved_parameter_profile import APPROVED_PARAMETER_PROFILE_WHITELIST, sha256_file
from bot.atomic_io import atomic_write_json, atomic_write_text
from bot.config import BotConfig
from tools.autonomous_live_run_common import now_iso


REPORT_OUT = Path("reports/live_learning/approved-parameter-profile-activation-latest.json")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _profile_payload(profile_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    return {"profile_name": profile_name, "profile_version": 1, "parameters": {str(k): str(v) for k, v in params.items()}}


def _hash_payload(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, indent=2).encode("utf-8") + b"\n").hexdigest()


def _select_candidate(payload: Any, profile_name: str = "") -> Dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("parameter_values"), dict):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
        candidates = [c for c in payload["candidates"] if isinstance(c, dict)]
        if profile_name:
            for candidate in candidates:
                if candidate.get("profile_name") == profile_name:
                    return candidate
        safe = [c for c in candidates if c.get("safe_to_activate_now")]
        return (safe or candidates or [{}])[0]
    if isinstance(payload, dict) and isinstance(payload.get("profiles"), dict):
        profiles = payload["profiles"]
        key = profile_name or "balanced_candidate_conservative"
        selected = profiles.get(key) if isinstance(profiles.get(key), dict) else {}
        return {"profile_name": key, "parameter_values": selected.get("candidate_params") or {}, "safe_to_activate_now": False}
    return {}


def build_activation_report(
    *,
    candidate_path: str | Path,
    profile_name: str = "",
    apply: bool = False,
    ack: str = "",
    write_env: bool = False,
    env_path: str | Path = ".env",
    root: str | Path = ".",
) -> Dict[str, Any]:
    project_root = Path(root)
    candidate_source = _load_json(Path(candidate_path))
    candidate = _select_candidate(candidate_source, profile_name=profile_name)
    selected_name = str(candidate.get("profile_name") or profile_name or "approved_parameter_profile")
    params = candidate.get("parameter_values") if isinstance(candidate.get("parameter_values"), dict) else {}
    payload = _profile_payload(selected_name, params)
    expected_hash = _hash_payload(payload)
    required_ack = f"ACTIVATE_APPROVED_PROFILE_{expected_hash[:12]}"
    blockers = []
    unknown = sorted(set(params) - APPROVED_PARAMETER_PROFILE_WHITELIST)
    if not params:
        blockers.append("candidate_parameters_missing")
    if unknown:
        blockers.append("unknown_parameter:" + ",".join(unknown))
    if not candidate.get("safe_to_activate_now"):
        blockers.append("candidate_not_marked_safe_to_activate_now")
    if apply and ack != required_ack:
        blockers.append("exact_ack_required")

    profile_path = project_root / "state/approved_parameter_profile.json"
    wrote_profile = False
    env_write_performed = False
    validation_result = {"status": "not_run", "error": ""}
    if apply and not blockers:
        atomic_write_json(profile_path, payload)
        wrote_profile = True
        actual_hash = sha256_file(profile_path)
        if actual_hash != expected_hash:
            blockers.append("written_profile_hash_mismatch")
        else:
            old_enabled = os.environ.get("ENABLE_APPROVED_PARAMETER_PROFILE")
            old_hash = os.environ.get("APPROVED_PARAMETER_PROFILE_HASH")
            try:
                os.environ["ENABLE_APPROVED_PARAMETER_PROFILE"] = "true"
                os.environ["APPROVED_PARAMETER_PROFILE_HASH"] = actual_hash
                cfg = BotConfig()
                cfg.validate()
                validation_result = {"status": "BOT_CONFIG_VALID", "error": ""}
            except Exception as exc:
                validation_result = {"status": "BOT_CONFIG_INVALID", "error": str(exc)}
                blockers.append("bot_config_invalid_after_profile_write")
            finally:
                if old_enabled is None:
                    os.environ.pop("ENABLE_APPROVED_PARAMETER_PROFILE", None)
                else:
                    os.environ["ENABLE_APPROVED_PARAMETER_PROFILE"] = old_enabled
                if old_hash is None:
                    os.environ.pop("APPROVED_PARAMETER_PROFILE_HASH", None)
                else:
                    os.environ["APPROVED_PARAMETER_PROFILE_HASH"] = old_hash
            if write_env and not blockers:
                path = Path(env_path)
                current = path.read_text(encoding="utf-8") if path.exists() else ""
                lines = [line for line in current.splitlines() if not line.startswith(("ENABLE_APPROVED_PARAMETER_PROFILE=", "APPROVED_PARAMETER_PROFILE_HASH="))]
                lines.extend(["ENABLE_APPROVED_PARAMETER_PROFILE=true", f"APPROVED_PARAMETER_PROFILE_HASH={actual_hash}"])
                atomic_write_text(path, "\n".join(lines) + "\n")
                env_write_performed = True

    return {
        "phase": "approved_parameter_profile_activation_v1",
        "generated_at": now_iso(),
        "candidate_path": str(candidate_path),
        "selected_profile_name": selected_name,
        "valid": not blockers,
        "blockers": blockers,
        "apply_requested": apply,
        "write_performed": wrote_profile,
        "env_write_performed": env_write_performed,
        "profile_path": str(profile_path),
        "approved_profile_json": payload,
        "hash": expected_hash,
        "required_ack": required_ack,
        "env_lines": ["ENABLE_APPROVED_PARAMETER_PROFILE=true", f"APPROVED_PARAMETER_PROFILE_HASH={expected_hash}"],
        "bot_config_validation": validation_result,
        "coinbase_call_attempted": False,
        "service_restart_attempted": False,
        "rollback_command": "python3 - <<'PY'\nfrom pathlib import Path\np=Path('.env')\ns=p.read_text() if p.exists() else ''\nlines=[x for x in s.splitlines() if not x.startswith(('ENABLE_APPROVED_PARAMETER_PROFILE=','APPROVED_PARAMETER_PROFILE_HASH='))]\nlines.append('ENABLE_APPROVED_PARAMETER_PROFILE=false')\np.write_text('\\n'.join(lines)+'\\n')\nPY",
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ACK-gated approved parameter profile activation.")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--profile", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--ack", default="")
    parser.add_argument("--write-env", action="store_true")
    parser.add_argument("--env-path", default=".env")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json-out", default=str(REPORT_OUT))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_activation_report(
        candidate_path=args.candidate,
        profile_name=args.profile,
        apply=args.apply,
        ack=args.ack,
        write_env=args.write_env,
        env_path=args.env_path,
        root=args.root,
    )
    atomic_write_json(Path(args.json_out), report)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"valid={report['valid']} apply={report['apply_requested']} hash={report['hash']} blockers={','.join(report['blockers'])}")
    return 0 if report["valid"] or not args.apply else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_activation_report", "main", "parse_args"]
