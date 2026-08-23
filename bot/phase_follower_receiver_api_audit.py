from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


PHASE_FOLLOWER_RECEIVER_API_AUDIT = "follower_receiver_api_audit_v1"
DEFAULT_FOLLOWER_PATHS = (
    "/opt/coinbase-replica",
    "/root/apps/Crypto/coinbase-replica",
)
TEXT_SUFFIXES = {".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".ini", ".cfg"}
ROUTE_RE = re.compile(
    r"@(?:app|router|api|bp)\.(?:get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
LITERAL_ROUTE_RE = re.compile(r"[\"'](/api/replica/[A-Za-z0-9_./{}-]+)[\"']")
SIGNATURE_HEADER_RE = re.compile(r"[\"']([xX][-A-Za-z0-9_]*signature[-A-Za-z0-9_]*)[\"']")
LIVE_DEFAULT_TRUE_RE = re.compile(
    r"(FOLLOWER_)?(LIVE|LIVE_MODE|ENABLE_LIVE|FOLLOWER_LIVE)[A-Z0-9_]*\s*=\s*(True|true|1)",
    re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _candidate_paths(root: Path, follower_paths: Optional[Sequence[str | Path]]) -> List[Path]:
    paths = [root / "replication"]
    explicit = list(follower_paths) if follower_paths is not None else list(DEFAULT_FOLLOWER_PATHS)
    paths.extend(Path(path) for path in explicit)
    sibling_root = root.parent
    try:
        for child in sibling_root.iterdir():
            if child.is_dir() and child.resolve() != root.resolve():
                lowered = child.name.lower()
                if "replica" in lowered or "follower" in lowered:
                    paths.append(child)
    except Exception:
        pass

    out: List[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def _iter_text_files(path: Path, *, max_files: int = 120) -> Iterable[Path]:
    if not path.exists() or not path.is_dir():
        return []
    files: List[Path] = []
    for child in path.rglob("*"):
        if len(files) >= max_files:
            break
        if "__pycache__" in child.parts or ".git" in child.parts:
            continue
        if child.is_file() and child.suffix.lower() in TEXT_SUFFIXES:
            files.append(child)
    return files


def _looks_like_receiver(path: Path, text: str) -> bool:
    lowered = text.lower()
    if "/api/replica/" in lowered and ("fastapi" in lowered or "flask" in lowered or "@app." in lowered or "@router." in lowered):
        return True
    name = path.name.lower()
    return ("receiver" in name or "api" in name or "server" in name) and "/api/replica/" in lowered


def _status_for_endpoint(endpoints: Iterable[str], endpoint: str) -> str:
    return "present" if endpoint in set(endpoints) else "missing"


def _contains_all(text: str, needles: Sequence[str]) -> bool:
    lowered = text.lower()
    return all(needle.lower() in lowered for needle in needles)


def _cap(items: Iterable[str], limit: int = 30) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _blocker_if(condition: bool, blocker: str) -> List[str]:
    return [] if condition else [blocker]


def build_follower_receiver_api_audit_report(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
    follower_paths: Optional[Sequence[str | Path]] = None,
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    checked_paths = _candidate_paths(project_root, follower_paths)

    paths_checked: List[Dict[str, Any]] = []
    files_inspected: List[Dict[str, Any]] = []
    receiver_files: List[Path] = []
    all_text_parts: List[str] = []
    receiver_text_parts: List[str] = []
    endpoints: List[str] = []
    receiver_endpoints: List[str] = []
    signature_headers: List[str] = []
    live_default_enabled = False

    for candidate in checked_paths:
        exists = candidate.exists()
        is_current_master_replication = candidate.resolve() == (project_root / "replication").resolve() if exists else False
        paths_checked.append(
            {
                "path": str(candidate),
                "exists": exists,
                "is_directory": candidate.is_dir() if exists else False,
                "role": "master_side_replication" if is_current_master_replication else "candidate_follower_receiver",
            }
        )
        if not exists or not candidate.is_dir():
            continue
        for text_file in _iter_text_files(candidate):
            text = _read_text(text_file)
            if not text:
                continue
            rel = str(text_file)
            local_endpoints = ROUTE_RE.findall(text) + LITERAL_ROUTE_RE.findall(text)
            endpoints.extend(local_endpoints)
            signature_headers.extend(SIGNATURE_HEADER_RE.findall(text))
            if LIVE_DEFAULT_TRUE_RE.search(text):
                live_default_enabled = True
            looks_receiver = _looks_like_receiver(text_file, text) and not is_current_master_replication
            if looks_receiver:
                receiver_files.append(text_file)
                receiver_text_parts.append(text)
                receiver_endpoints.extend(local_endpoints)
            if looks_receiver or "/api/replica/" in text or "follower" in text.lower() or "hmac" in text.lower():
                files_inspected.append(
                    {
                        "path": rel,
                        "bytes": text_file.stat().st_size,
                        "looks_like_receiver": looks_receiver,
                        "endpoints": _cap(local_endpoints, 12),
                    }
                )
                all_text_parts.append(text)

    combined = "\n".join(all_text_parts)
    receiver_combined = "\n".join(receiver_text_parts)
    lowered = combined.lower()
    receiver_lowered = receiver_combined.lower()
    endpoints = _cap(endpoints, 60)
    receiver_endpoints = _cap(receiver_endpoints, 60)
    signature_headers = _cap(signature_headers, 12)
    receiver_code_found = bool(receiver_files)

    decision_status = _status_for_endpoint(receiver_endpoints, "/api/replica/decision")
    lifecycle_status = _status_for_endpoint(receiver_endpoints, "/api/replica/lifecycle")
    health_state_reconcile = [
        endpoint for endpoint in receiver_endpoints if any(token in endpoint.lower() for token in ("health", "state", "reconcile"))
    ]

    hmac_required = bool(
        receiver_code_found
        and ("hmac" in receiver_lowered or "compare_digest" in receiver_lowered)
        and (signature_headers or "x-replica-signature" in lowered)
    )
    idempotency_present = any(token in receiver_lowered for token in ("idempot", "event_id", "dedup", "nonce", "replay"))
    paper_mode_present = "paper" in receiver_lowered or "dry_run" in receiver_lowered or "observe" in receiver_lowered
    live_gate_present = any(
        token in receiver_lowered for token in ("ack", "enable_live", "follower_live", "live_allowed", "dry_run")
    )

    buy_checks = {
        "product_rules": any(token in receiver_lowered for token in ("product_rule", "base_increment", "quote_increment")),
        "balance_checks": "balance" in receiver_lowered,
        "caps": any(token in receiver_lowered for token in ("cap", "max_notional", "max_order")),
        "min_size_increment": any(
            token in receiver_lowered for token in ("min_size", "base_increment", "quote_increment", "increment")
        ),
        "idempotency": idempotency_present,
        "drift_reconcile": any(token in receiver_lowered for token in ("drift", "reconcile")),
    }
    sell_checks = {
        "no_oversell": any(
            token in receiver_lowered for token in ("no_oversell", "oversell", "position_size", "available_base")
        ),
        "reduce_only": "reduce" in receiver_lowered,
        "reservation_governance": any(
            token in receiver_lowered for token in ("reservation", "reserved_base", "open_exit")
        ),
        "drift_reconcile": buy_checks["drift_reconcile"],
        "live_sell_ack": "sell" in receiver_lowered and "ack" in receiver_lowered,
    }
    follower_buy_ready = receiver_code_found and hmac_required and all(buy_checks.values()) and paper_mode_present and live_gate_present
    follower_sell_ready = follower_buy_ready and all(sell_checks.values())
    lifecycle_support = {
        "decision_event_support": decision_status == "present",
        "replication_lifecycle_v1_support": lifecycle_status == "present" and "replication.lifecycle.v1" in receiver_lowered,
        "c4_handling": any(token in receiver_lowered for token in ("c4", "entry_order")),
        "d1_handling": any(token in receiver_lowered for token in ("d1", "fill_to_position")),
        "d2_handling": any(token in receiver_lowered for token in ("d2", "position_plan")),
        "d3_handling": any(token in receiver_lowered for token in ("d3", "exit_intent", "exit_preview")),
        "d4_handling": any(token in receiver_lowered for token in ("d4", "cancel_replace", "reprice")),
        "d5_handling": any(token in receiver_lowered for token in ("d5", "metric", "execution_evidence")),
        "governance_handling": "governance" in receiver_lowered,
        "d3_d4_observe_only_default": _contains_all(receiver_lowered, ("d3", "observe"))
        or _contains_all(receiver_lowered, ("d4", "observe"))
        or _contains_all(receiver_lowered, ("exit", "observe")),
        "unknown_event_fail_closed": any(
            token in receiver_lowered for token in ("unknown_event", "unsupported", "fail_closed", "raise", "400")
        ),
    }
    lifecycle_parity_ready = receiver_code_found and all(lifecycle_support.values())

    blockers: List[str] = []
    blockers.extend(_blocker_if(receiver_code_found, "follower_receiver_code_not_accessible"))
    blockers.extend(_blocker_if(decision_status == "present", "decision_endpoint_missing"))
    blockers.extend(_blocker_if(lifecycle_status == "present", "lifecycle_endpoint_missing"))
    blockers.extend(_blocker_if(hmac_required, "hmac_signature_verification_not_proven"))
    blockers.extend(_blocker_if(idempotency_present, "idempotency_or_replay_protection_not_proven"))
    blockers.extend(_blocker_if(paper_mode_present and live_gate_present and not live_default_enabled, "paper_live_separation_not_proven"))
    for key, value in buy_checks.items():
        if not value:
            blockers.append(f"buy_check_missing:{key}")
    for key, value in sell_checks.items():
        if not value:
            blockers.append(f"sell_check_missing:{key}")
    if not lifecycle_parity_ready:
        blockers.append("lifecycle_parity_not_proven")
    if live_default_enabled:
        blockers.append("unsafe_follower_live_default_enabled")

    if live_default_enabled:
        classification = "STOP_NOW"
    elif blockers:
        classification = "WATCH"
    else:
        classification = "OK"

    audit_complete = receiver_code_found and classification != "STOP_NOW" and not blockers
    remote_checklist = [
        "Provide follower receiver/API repository path for local static audit.",
        "Run endpoint contract tests for /api/replica/decision and /api/replica/lifecycle without starting live services.",
        "Prove HMAC verification, timestamp/replay rejection and idempotent event_id handling.",
        "Prove paper mode is default and live BUY/SELL require separate exact ACK gates.",
        "Prove product rules, balances, caps, min size/increment, no-oversell and drift/reconcile checks.",
        "Prove D3/D4 lifecycle events are observe-only by default and unknown events fail closed.",
    ]

    return _json_safe(
        {
            "phase": PHASE_FOLLOWER_RECEIVER_API_AUDIT,
            "generated_at": generated_at or _now_iso(),
            "metadata": {
                "report_only": True,
                "local_files_only": True,
                "coinbase_call_attempted": False,
                "http_call_attempted": False,
                "state_write_performed": False,
            },
            "classification": classification,
            "blockers": sorted(set(blockers)),
            "follower_code_discovery": {
                "paths_checked": paths_checked,
                "receiver_code_found": receiver_code_found,
                "follower_receiver_code_accessible": receiver_code_found,
                "files_inspected": files_inspected,
                "receiver_files": [str(path) for path in receiver_files],
                "missing_reason": "" if receiver_code_found else "No separate follower receiver/API repo was accessible from checked local paths; only master-side replication code was visible.",
            },
            "endpoint_audit": {
                "endpoints_found": endpoints,
                "receiver_endpoints_found": receiver_endpoints,
                "decision_endpoint_status": decision_status,
                "lifecycle_endpoint_status": lifecycle_status,
                "health_state_reconcile_endpoints": health_state_reconcile,
            },
            "auth_hmac_audit": {
                "hmac_required": hmac_required,
                "signature_header_names": signature_headers,
                "replay_idempotency_present": idempotency_present,
                "missing_risks": [
                    risk
                    for risk, missing in (
                        ("hmac_verification_missing_or_unknown", not hmac_required),
                        ("replay_or_idempotency_missing_or_unknown", not idempotency_present),
                    )
                    if missing
                ],
            },
            "mode_separation": {
                "paper_live_mode_separation_status": "proven" if paper_mode_present and live_gate_present and not live_default_enabled else "missing_or_unknown",
                "default_mode": "unsafe_live" if live_default_enabled else "paper_or_unknown",
                "live_action_gates_present": live_gate_present,
                "ack_requirements_present": "ack" in lowered,
                "unsafe_live_default_detected": live_default_enabled,
            },
            "buy_readiness": {
                "follower_buy_ready": follower_buy_ready,
                "checks": buy_checks,
                "blockers": [item for item in blockers if item.startswith("buy_check_missing:")],
            },
            "sell_readiness": {
                "follower_sell_ready": follower_sell_ready,
                "checks": sell_checks,
                "blockers": [item for item in blockers if item.startswith("sell_check_missing:")],
            },
            "lifecycle_parity": {
                "lifecycle_parity_ready": lifecycle_parity_ready,
                "support": lifecycle_support,
                "d3_d4_observe_only_default": lifecycle_support["d3_d4_observe_only_default"],
                "unknown_event_fail_closed": lifecycle_support["unknown_event_fail_closed"],
            },
            "readiness_flags": {
                "follower_receiver_code_accessible": receiver_code_found,
                "follower_receiver_api_audit_complete": audit_complete,
                "follower_ready_for_paper_lifecycle_test": True,
                "follower_buy_ready": follower_buy_ready,
                "follower_sell_ready": follower_sell_ready,
                "follower_ready_for_live": False,
                "lifecycle_parity_ready": lifecycle_parity_ready,
                "replication_enabled": False,
                "follower_live_enabled": False,
            },
            "remote_audit_checklist": remote_checklist,
            "recommended_next_sprint": {
                "route": "selected_test_expansion_in_safe_regression_harness",
                "why": "Follower receiver/API code is not accessible or not complete from local files, so the next safe progress point is consolidating selected contract/readiness tests in the local harness without live or HTTP actions.",
            },
        }
    )


def render_follower_receiver_api_audit_markdown(report: Dict[str, Any]) -> str:
    metadata = report.get("metadata") or {}
    discovery = report.get("follower_code_discovery") or {}
    endpoints = report.get("endpoint_audit") or {}
    auth = report.get("auth_hmac_audit") or {}
    mode = report.get("mode_separation") or {}
    buy = report.get("buy_readiness") or {}
    sell = report.get("sell_readiness") or {}
    lifecycle = report.get("lifecycle_parity") or {}
    flags = report.get("readiness_flags") or {}
    lines = [
        "# Follower Receiver/API Audit",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- report_only: `{metadata.get('report_only')}`",
        f"- local_files_only: `{metadata.get('local_files_only')}`",
        f"- coinbase_call_attempted: `{metadata.get('coinbase_call_attempted')}`",
        f"- http_call_attempted: `{metadata.get('http_call_attempted')}`",
        f"- state_write_performed: `{metadata.get('state_write_performed')}`",
        "",
        "## Code Discovery",
        "",
        f"- follower_receiver_code_accessible: `{discovery.get('follower_receiver_code_accessible')}`",
        f"- receiver_files: `{'; '.join(discovery.get('receiver_files') or [])}`",
        f"- missing_reason: `{discovery.get('missing_reason')}`",
        "",
        "## Endpoints",
        "",
        f"- endpoints_found: `{'; '.join(endpoints.get('endpoints_found') or [])}`",
        f"- decision_endpoint_status: `{endpoints.get('decision_endpoint_status')}`",
        f"- lifecycle_endpoint_status: `{endpoints.get('lifecycle_endpoint_status')}`",
        f"- health_state_reconcile_endpoints: `{'; '.join(endpoints.get('health_state_reconcile_endpoints') or [])}`",
        "",
        "## Auth And Mode",
        "",
        f"- hmac_required: `{auth.get('hmac_required')}`",
        f"- signature_header_names: `{'; '.join(auth.get('signature_header_names') or [])}`",
        f"- replay_idempotency_present: `{auth.get('replay_idempotency_present')}`",
        f"- paper_live_mode_separation_status: `{mode.get('paper_live_mode_separation_status')}`",
        f"- default_mode: `{mode.get('default_mode')}`",
        f"- unsafe_live_default_detected: `{mode.get('unsafe_live_default_detected')}`",
        "",
        "## Readiness",
        "",
        f"- follower_buy_ready: `{buy.get('follower_buy_ready')}`",
        f"- follower_sell_ready: `{sell.get('follower_sell_ready')}`",
        f"- lifecycle_parity_ready: `{lifecycle.get('lifecycle_parity_ready')}`",
        f"- follower_ready_for_live: `{flags.get('follower_ready_for_live')}`",
        "",
        "## Blockers",
        "",
    ]
    for blocker in report.get("blockers") or []:
        lines.append(f"- {blocker}")
    lines.extend(["", "## Remote Audit Checklist", ""])
    for item in report.get("remote_audit_checklist") or []:
        lines.append(f"- {item}")
    next_sprint = report.get("recommended_next_sprint") or {}
    lines.extend(
        [
            "",
            "## Recommended Next Sprint",
            "",
            f"- route: `{next_sprint.get('route')}`",
            f"- why: {next_sprint.get('why')}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_FOLLOWER_RECEIVER_API_AUDIT",
    "build_follower_receiver_api_audit_report",
    "render_follower_receiver_api_audit_markdown",
]
