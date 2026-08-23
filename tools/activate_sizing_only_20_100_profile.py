#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.approved_parameter_profile import APPROVED_PARAMETER_PROFILE_WHITELIST, sha256_file
from bot.atomic_io import atomic_write_json, atomic_write_text
from bot.config import BotConfig
from tools.show_open_orders import OPEN_STATUSES, load_orders


ACK = "ACK_ACTIVATE_SIZING_ONLY_20_100_NO_REPLICATION"
PROFILE_NAME = "sizing_only_20_100_conservative_v1"
DEFAULT_CANDIDATE_OUT = Path("reports/backtests/sizing-only-20-100-approved-profile-candidate.json")
DEFAULT_REPORT_JSON = Path("reports/live_runs/sizing-only-20-100-activation-latest.json")
DEFAULT_REPORT_MD = Path("reports/live_runs/sizing-only-20-100-activation-latest.md")

PROFILE_PARAMETERS = {
    # Must stay >= bot.live_order_size_policy.MIN_LIVE_ORDER_QUOTE_USDC
    # (50.00), which BotConfig.validate() enforces unconditionally.
    "DEFAULT_QUOTE_SIZE_USDC": "50.00",
    "MAX_NOTIONAL_USD": "100.00",
    "AUTONOMOUS_MAX_ORDER_QUOTE": "100.00",
    "PHASE_C_MAX_ORDER_QUOTE": "100.00",
    "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "100.00",
    "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
    "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
    "MAX_OPEN_POSITIONS": "3",
    "MAX_SPREAD_PCT": "0.0060",
    "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0125",
    "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": "3.0",
    "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": "1.5",
    "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": "0.0350",
}

FALSE_FLAGS = {
    "REPLICATION_ENABLED": "false",
    "REPLICATION_LIFECYCLE_ENABLED": "false",
    "REPLICATION_LIFECYCLE_HTTP_ENABLED": "false",
    "MARKET_ORDER_ENABLED": "false",
    "ENABLE_MARKET_ORDERS": "false",
    "ALLOW_MARKET_ORDERS": "false",
    "LEARNING_TO_EXECUTION_ALLOWED": "false",
    "LIVE_LEARNING_ALLOWED": "false",
    "PARAMETER_CHANGE_ALLOWED": "false",
    "NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED": "false",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def approved_profile_json() -> Dict[str, Any]:
    return {
        "profile_name": PROFILE_NAME,
        "profile_version": 1,
        "parameters": dict(PROFILE_PARAMETERS),
    }


def canonical_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_candidate_payload(*, generated_at: Optional[str] = None) -> Dict[str, Any]:
    payload = approved_profile_json()
    unknown = sorted(set(payload["parameters"]) - APPROVED_PARAMETER_PROFILE_WHITELIST)
    return {
        "phase": "sizing_only_20_100_approved_profile_candidate_v1",
        "generated_at": generated_at or _now_iso(),
        "profile_name": PROFILE_NAME,
        "safe_to_live_activate_now": True,
        "requires_operator_review": True,
        "requires_exact_hash_ack": True,
        "activation_scope": "sizing_only",
        "d2_thresholds_changed": False,
        "replication_enabled": False,
        "market_orders_enabled": False,
        "unknown_parameter_keys": unknown,
        "parameter_values": dict(PROFILE_PARAMETERS),
        "approved_profile_json": payload,
        "candidate_hash_to_review": canonical_hash(payload),
        "required_ack": ACK,
        "coinbase_call_attempted": False,
        "service_touched": False,
        "env_write_performed": False,
        "state_write_performed": False,
    }


def write_candidate(path: str | Path = DEFAULT_CANDIDATE_OUT) -> Dict[str, Any]:
    candidate = build_candidate_payload()
    atomic_write_json(Path(path), candidate)
    return candidate


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _env_map(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    out: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _enabled(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _open_position_summary(path: Path) -> Dict[str, Any]:
    payload = _load_json(path)
    rows = payload.values() if isinstance(payload, dict) else []
    open_rows = []
    incoherent = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").lower()
        base = str(row.get("position_size_base") or row.get("bot_managed_base") or "0")
        if status in {"open", "active", "monitoring"} and base not in {"", "0", "0.0", "0.00"}:
            open_rows.append({"ticker": row.get("ticker"), "status": status, "position_size_base": base})
        if status in {"open", "active", "monitoring"} and base in {"", "0", "0.0", "0.00"}:
            incoherent.append({"ticker": row.get("ticker"), "status": status, "position_size_base": base})
    return {
        "open_positions": len(open_rows),
        "open_position_rows": open_rows,
        "coherent": not incoherent,
        "incoherent_rows": incoherent,
    }


def _open_orders_summary(path: Path) -> Dict[str, Any]:
    orders = load_orders(path)
    open_orders = [o for o in orders if str(o.get("status", "")).lower() in OPEN_STATUSES]
    return {"open_orders": len(open_orders), "orders": open_orders[:10]}


def _update_env(path: Path, updates: Dict[str, str]) -> Dict[str, Any]:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = existing.splitlines()
    seen = set()
    out = []
    changed = {}
    for line in lines:
        if "=" not in line or line.strip().startswith("#"):
            out.append(line)
            continue
        key, _value = line.split("=", 1)
        key = key.strip()
        if key in updates:
            old = line.split("=", 1)[1].strip()
            new = updates[key]
            out.append(f"{key}={new}")
            seen.add(key)
            if old != new:
                changed[key] = {"old": old if key not in {"APPROVED_PARAMETER_PROFILE_HASH"} else "<hash>", "new": new if key not in {"APPROVED_PARAMETER_PROFILE_HASH"} else "<hash>"}
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
            changed[key] = {"old": "<missing>", "new": value if key != "APPROVED_PARAMETER_PROFILE_HASH" else "<hash>"}
    atomic_write_text(path, "\n".join(out).rstrip() + "\n")
    return {"changed": changed, "keys_written": sorted(updates)}


def build_activation_report(
    *,
    root: str | Path = ".",
    candidate_path: str | Path = DEFAULT_CANDIDATE_OUT,
    ack: str = "",
    apply: bool = False,
    write_env: bool = False,
    env_path: str | Path = ".env",
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    project_root = Path(root)
    candidate_file = project_root / Path(candidate_path)
    if not candidate_file.exists():
        candidate = write_candidate(candidate_file)
    else:
        candidate = _load_json(candidate_file)
    approved_payload = candidate.get("approved_profile_json") if isinstance(candidate, dict) else {}
    expected_candidate_hash = canonical_hash(approved_payload) if isinstance(approved_payload, dict) else ""
    blockers = []

    if ack != ACK:
        blockers.append("exact_ack_missing")
    if candidate.get("profile_name") != PROFILE_NAME:
        blockers.append("candidate_profile_name_mismatch")
    if candidate.get("candidate_hash_to_review") != expected_candidate_hash:
        blockers.append("candidate_hash_mismatch")
    if not candidate.get("safe_to_live_activate_now"):
        blockers.append("candidate_not_safe_to_live_activate_now")
    if candidate.get("activation_scope") != "sizing_only":
        blockers.append("candidate_scope_not_sizing_only")
    if candidate.get("d2_thresholds_changed"):
        blockers.append("d2_thresholds_changed")
    unknown = sorted(set((approved_payload.get("parameters") or {}).keys()) - APPROVED_PARAMETER_PROFILE_WHITELIST)
    if unknown:
        blockers.append("unknown_parameter:" + ",".join(unknown))

    env_values = _env_map(project_root / Path(env_path))
    enabled_false_flags = {key: env_values.get(key, "false") for key in FALSE_FLAGS}
    for key, value in enabled_false_flags.items():
        if _enabled(value):
            blockers.append(f"{key}_enabled")

    open_orders = _open_orders_summary(project_root / "state/open_orders.json")
    positions = _open_position_summary(project_root / "state/positions.json")
    if open_orders["open_orders"] != 0:
        blockers.append("open_orders_not_zero")
    if not positions["coherent"]:
        blockers.append("positions_incoherent")

    validation = {"status": "not_run", "error": ""}
    env_changes = {"changed": {}, "keys_written": []}
    wrote_profile = False
    env_write_performed = False
    active_before = _load_json(project_root / "state/approved_parameter_profile.json")
    active_after = active_before
    new_file_hash = ""
    if apply and not blockers:
        profile_path = project_root / "state/approved_parameter_profile.json"
        atomic_write_json(profile_path, approved_payload)
        wrote_profile = True
        new_file_hash = sha256_file(profile_path)
        old_env = {key: os.environ.get(key) for key in ["ENABLE_APPROVED_PARAMETER_PROFILE", "APPROVED_PARAMETER_PROFILE_HASH"]}
        old_false = {key: os.environ.get(key) for key in FALSE_FLAGS}
        old_cwd = Path.cwd()
        try:
            os.environ["ENABLE_APPROVED_PARAMETER_PROFILE"] = "true"
            os.environ["APPROVED_PARAMETER_PROFILE_HASH"] = new_file_hash
            for key, value in FALSE_FLAGS.items():
                os.environ[key] = value
            os.chdir(project_root)
            BotConfig().validate()
            validation = {"status": "BOT_CONFIG_VALID", "error": ""}
        except Exception as exc:
            validation = {"status": "BOT_CONFIG_INVALID", "error": str(exc)}
            blockers.append("bot_config_invalid_after_profile_write")
        finally:
            try:
                os.chdir(old_cwd)
            except Exception:
                pass
            for key, old in old_env.items():
                if old is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old
            for key, old in old_false.items():
                if old is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old
        if write_env and not blockers:
            updates = {"ENABLE_APPROVED_PARAMETER_PROFILE": "true", "APPROVED_PARAMETER_PROFILE_HASH": new_file_hash}
            updates.update(FALSE_FLAGS)
            env_changes = _update_env(project_root / Path(env_path), updates)
            env_write_performed = True
        active_after = _load_json(profile_path)

    return {
        "phase": "sizing_only_20_100_activation_v1",
        "generated_at": generated_at or _now_iso(),
        "ack_required": ACK,
        "ack_present": ack == ACK,
        "apply_requested": apply,
        "activation_performed": wrote_profile and not blockers,
        "state_write_performed": wrote_profile,
        "env_write_performed": env_write_performed,
        "coinbase_action_attempted": False,
        "manual_coinbase_order_action_attempted": False,
        "service_restart_attempted": False,
        "service_restart_performed": False,
        "candidate_path": str(candidate_file),
        "candidate_hash_to_review": expected_candidate_hash,
        "approved_profile_file_hash": new_file_hash,
        "active_profile_before": active_before,
        "active_profile_after": active_after,
        "candidate": candidate,
        "preflight": {
            "open_orders": open_orders,
            "positions": positions,
            "env_false_flags": enabled_false_flags,
            "market_orders_disabled": not any(_enabled(env_values.get(k, "false")) for k in ["MARKET_ORDER_ENABLED", "ENABLE_MARKET_ORDERS", "ALLOW_MARKET_ORDERS"]),
            "replication_disabled": not any(_enabled(env_values.get(k, "false")) for k in ["REPLICATION_ENABLED", "REPLICATION_LIFECYCLE_ENABLED", "REPLICATION_LIFECYCLE_HTTP_ENABLED"]),
            "neural_execution_disabled": not _enabled(env_values.get("NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED", "false")),
            "learning_direct_mutation_disabled": not any(_enabled(env_values.get(k, "false")) for k in ["LEARNING_TO_EXECUTION_ALLOWED", "LIVE_LEARNING_ALLOWED", "PARAMETER_CHANGE_ALLOWED"]),
        },
        "blockers": blockers,
        "bot_config_validation": validation,
        "env_changes": env_changes,
        "rollback_commands": [
            "Restore the previous state/approved_parameter_profile.json from git or backup.",
            "Set APPROVED_PARAMETER_PROFILE_HASH back to the previous state file hash, or set ENABLE_APPROVED_PARAMETER_PROFILE=false.",
            "Do not restart coinbase-bot until BotConfig validate and readiness are green.",
        ],
    }


def _render_report(report: Dict[str, Any]) -> str:
    before = report.get("active_profile_before") or {}
    after = report.get("active_profile_after") or {}
    lines = [
        "# Sizing Only 20-100 Activation",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        f"- Activation performed: `{report['activation_performed']}`",
        f"- Candidate hash: `{report['candidate_hash_to_review']}`",
        f"- Approved profile file hash: `{report['approved_profile_file_hash']}`",
        f"- BotConfig validation: `{report['bot_config_validation']['status']}`",
        f"- Blockers: `{', '.join(report['blockers']) or 'none'}`",
        f"- Service restart performed: `{report['service_restart_performed']}`",
        "",
        "## Active Profile Before",
        "",
        "```json",
        json.dumps(before, indent=2, sort_keys=True),
        "```",
        "",
        "## Active Profile After",
        "",
        "```json",
        json.dumps(after, indent=2, sort_keys=True),
        "```",
        "",
        "## Env Changes",
        "",
        "```json",
        json.dumps(report.get("env_changes"), indent=2, sort_keys=True),
        "```",
        "",
        "## Safety",
        "",
        "- Replication remains disabled.",
        "- Market orders remain disabled.",
        "- Neural execution remains disabled.",
        "- No manual Coinbase BUY/SELL/cancel/replace/apply attempted.",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and optionally activate sizing-only 20-100 approved profile.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--candidate-out", default=str(DEFAULT_CANDIDATE_OUT))
    parser.add_argument("--json-out", default=str(DEFAULT_REPORT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_REPORT_MD))
    parser.add_argument("--ack", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--write-env", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    candidate = write_candidate(Path(args.root) / Path(args.candidate_out))
    report = build_activation_report(
        root=args.root,
        candidate_path=args.candidate_out,
        ack=args.ack,
        apply=args.apply,
        write_env=args.write_env,
    )
    atomic_write_json(Path(args.root) / Path(args.json_out), report)
    atomic_write_text(Path(args.root) / Path(args.md_out), _render_report(report))
    print(json.dumps({
        "candidate_hash_to_review": candidate["candidate_hash_to_review"],
        "activation_performed": report["activation_performed"],
        "blockers": report["blockers"],
        "approved_profile_file_hash": report["approved_profile_file_hash"],
    }, indent=2, sort_keys=True))
    return 0 if not report["blockers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ACK",
    "PROFILE_NAME",
    "PROFILE_PARAMETERS",
    "approved_profile_json",
    "build_activation_report",
    "build_candidate_payload",
    "canonical_hash",
    "main",
    "parse_args",
    "write_candidate",
]
