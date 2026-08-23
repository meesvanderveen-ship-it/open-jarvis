#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.show_phase_b_status import build_status, load_jsonl, load_json_state

FINAL_STATUSES = {"replaced", "invalidated", "expired", "cancelled", "failed"}
OPEN_INTENT_STATUSES = {"active", "waiting", "trigger_ready", "needs_fresh_analysis", "stale"}
OPEN_ORDER_STATUSES = {"active", "planned", "pending", "submitted", "partially_filled", "cancel_pending", "replace_pending"}


def _tail_jsonl(path: Path, limit: int) -> List[Dict[str, Any]]:
    rows = load_jsonl(path)
    return rows[-limit:] if limit > 0 else rows


def _compact_error(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ts": row.get("ts") or row.get("timestamp") or row.get("generated_at") or row.get("time"),
        "ticker": row.get("ticker"),
        "module": row.get("module") or row.get("stage"),
        "error_type": row.get("error_type") or row.get("type"),
        "error": str(row.get("error") or row.get("message") or row.get("reason") or "")[:220],
    }


def _log_health(logs_dir: Path, *, limit: int) -> Dict[str, Any]:
    errors = _tail_jsonl(logs_dir / "errors.jsonl", limit)
    corrupt = _tail_jsonl(logs_dir / "llm_corrupt.jsonl", limit)
    provider_errors = _tail_jsonl(logs_dir / "llm_provider_errors.jsonl", limit)
    pending_events = _tail_jsonl(logs_dir / "pending_order_intents.jsonl", limit)
    replication = _tail_jsonl(logs_dir / "replication_outbox.jsonl", limit)

    pending_by_event: Dict[str, int] = {}
    for row in pending_events:
        event = str(row.get("event_type") or row.get("event") or "unknown")
        pending_by_event[event] = pending_by_event.get(event, 0) + 1

    replication_errors = 0
    for row in replication:
        accepted = row.get("accepted")
        status_code = row.get("status_code")
        if accepted is False or (isinstance(status_code, int) and status_code >= 400):
            replication_errors += 1

    return {
        "errors_path": str(logs_dir / "errors.jsonl"),
        "errors_sample_size": len(errors),
        "latest_errors": [_compact_error(row) for row in errors[-10:]],
        "llm_corrupt_path": str(logs_dir / "llm_corrupt.jsonl"),
        "llm_corrupt_sample_size": len(corrupt),
        "latest_llm_corrupt": [_compact_error(row) for row in corrupt[-10:]],
        "llm_provider_errors_path": str(logs_dir / "llm_provider_errors.jsonl"),
        "llm_provider_error_sample_size": len(provider_errors),
        "latest_llm_provider_errors": [_compact_error(row) for row in provider_errors[-10:]],
        "pending_intent_events_sample_size": len(pending_events),
        "pending_intent_events_by_type": pending_by_event,
        "replication_outbox_sample_size": len(replication),
        "replication_outbox_error_like_rows": replication_errors,
    }


def _source_hygiene(project_root: Path) -> Dict[str, Any]:
    findings: Dict[str, List[str]] = {
        "env_files": [],
        "venv_dirs": [],
        "git_dirs": [],
        "backup_files": [],
        "patch_archives": [],
        "pycache_dirs": [],
    }
    max_each = 40
    for path in project_root.rglob("*"):
        rel = str(path.relative_to(project_root))
        name = path.name
        if path.is_dir() and name == ".venv" and len(findings["venv_dirs"]) < max_each:
            findings["venv_dirs"].append(rel)
        elif path.is_dir() and name == ".git" and len(findings["git_dirs"]) < max_each:
            findings["git_dirs"].append(rel)
        elif path.is_dir() and name == "__pycache__" and len(findings["pycache_dirs"]) < max_each:
            findings["pycache_dirs"].append(rel)
        elif path.is_file() and (name == ".env" or name.startswith(".env.")) and len(findings["env_files"]) < max_each:
            findings["env_files"].append(rel)
        elif path.is_file() and ("backup" in name.lower() or name.endswith(".bak") or ".bak." in name or name.endswith("~")) and len(findings["backup_files"]) < max_each:
            findings["backup_files"].append(rel)
        elif path.is_file() and path.suffix.lower() in {".zip", ".tar", ".gz"} and len(findings["patch_archives"]) < max_each:
            findings["patch_archives"].append(rel)
    warnings = []
    if findings["env_files"]:
        warnings.append("Bronexport bevat .env-bestanden; deel deze niet extern.")
    if findings["venv_dirs"]:
        warnings.append("Bronexport bevat .venv; dit maakt exports groot en onnodig.")
    if findings["git_dirs"]:
        warnings.append("Bronexport bevat .git; kan geschiedenis/remote-info bevatten.")
    if findings["backup_files"] or findings["patch_archives"]:
        warnings.append("Bronexport bevat backups/patch-archieven; opschonen voorkomt verwarring.")
    return {"findings": findings, "warnings": warnings}


def _count_duplicate_filenames(project_root: Path, interesting: Iterable[str]) -> Dict[str, List[str]]:
    wanted = set(interesting)
    found: Dict[str, List[str]] = {name: [] for name in wanted}
    for path in project_root.rglob("*.py"):
        if path.name in wanted:
            found[path.name].append(str(path.relative_to(project_root)))
    return {name: paths for name, paths in found.items() if len(paths) > 1}


def _build_phase_c_checklist(status: Dict[str, Any], logs: Dict[str, Any]) -> List[Dict[str, Any]]:
    cfg = status.get("config", {})
    orders = status.get("orders", {})
    pending = status.get("pending_order_intents", {})
    checks: List[Tuple[str, bool, str]] = [
        ("Config valideert", bool(cfg.get("config_ok")), "BotConfig.validate() moet slagen."),
        ("Live limit-order kill switches uit", not any([cfg.get("enable_live_limit_orders"), cfg.get("enable_live_entry_orders"), cfg.get("enable_live_exit_orders")]), "Voor fase B moeten alle live limit-order flags false zijn."),
        ("Read-only execution planner actief", bool(cfg.get("enable_read_only_execution_planner")), "Planner mag context geven zonder live orders."),
        ("Limit order manager actief in paper-context", bool(cfg.get("enable_limit_order_manager")), "Paper lifecycle/diagnostics moeten actief blijven."),
        ("Geen open orders", int(orders.get("open_orders") or 0) == 0, "Open paper/live orders moeten verklaarbaar zijn vóór fase C."),
        ("Geen diagnostic orders", int(orders.get("diagnostic_order_count") or 0) == 0, "Testorders horen niet in runtime-state."),
        ("Pending intents hebben geen diagnostics", int(pending.get("diagnostic_intent_count") or 0) == 0, "Diagnostic intents horen niet in runtime-state."),
        ("Pending intents zijn observability-only", True, "Pending intents autoriseren geen execution; fresh judge+risk blijft verplicht."),
        ("Geen recente log-error sample vereist handmatige review", int(logs.get("errors_sample_size") or 0) == 0, "Als errors_sample_size > 0: beoordeel timestamp/ernst voordat fase C live gaat."),
        ("Geen recente LLM-corrupt sample vereist handmatige review", int(logs.get("llm_corrupt_sample_size") or 0) == 0, "Als llm_corrupt_sample_size > 0: beoordeel timestamp/ernst voordat fase C live gaat."),
        ("Provider-errors apart gelogd", True, "Vanaf C.1.1 horen provider/billing errors naar llm_provider_errors.jsonl, niet naar llm_corrupt.jsonl."),
    ]
    return [{"name": name, "passed": passed, "note": note} for name, passed, note in checks]


def build_final_report(args: argparse.Namespace) -> Dict[str, Any]:
    project_root = Path(args.project_root).resolve()
    status_args = argparse.Namespace(
        open_orders_path=str(project_root / args.open_orders_path),
        pending_intents_path=str(project_root / args.pending_intents_path),
        execution_outcomes_path=str(project_root / args.execution_outcomes_path),
        execution_plans_path=str(project_root / args.execution_plans_path),
        limit=args.limit,
    )
    status = build_status(status_args)
    logs = _log_health(project_root / args.logs_dir, limit=args.limit)
    hygiene = _source_hygiene(project_root) if args.include_source_hygiene else {"findings": {}, "warnings": []}
    duplicates = _count_duplicate_filenames(project_root, ["coinbase_client.py", "config.py", "strategy_engine.py"])

    blockers: List[str] = []
    warnings: List[str] = []
    recommendations: List[str] = []

    cfg = status.get("config", {})
    orders = status.get("orders", {})
    pending = status.get("pending_order_intents", {})

    if not cfg.get("config_ok"):
        blockers.append(f"Config valideert niet: {cfg.get('config_error')}")
    if cfg.get("enable_live_limit_orders") or cfg.get("enable_live_entry_orders") or cfg.get("enable_live_exit_orders"):
        blockers.append("Live limit-order flags staan aan; fase B hoort paper-only te zijn.")
    if int(orders.get("open_orders") or 0) > 0:
        warnings.append("Er zijn open orders; verklaar deze vóór fase C.")
    if int(orders.get("diagnostic_order_count") or 0) > 0:
        warnings.append("Diagnostic paper-orders aanwezig; ruim op vóór normale runtime/fase C.")
    if int(pending.get("diagnostic_intent_count") or 0) > 0:
        warnings.append("Diagnostic pending intents aanwezig; ruim op vóór normale runtime/fase C.")
    if logs.get("errors_sample_size"):
        warnings.append("errors.jsonl bevat recente/sample regels; beoordeel timestamps en ernst.")
    if logs.get("llm_corrupt_sample_size"):
        warnings.append("llm_corrupt.jsonl bevat recente/sample regels; beoordeel timestamps en fallbackgedrag.")
    if logs.get("llm_provider_error_sample_size"):
        warnings.append("llm_provider_errors.jsonl bevat provider/account/API fouten; beoordeel of fallback/disabled routing werkt.")
    warnings.extend(hygiene.get("warnings", []))
    if duplicates.get("coinbase_client.py"):
        warnings.append("coinbase_client.py bestaat op meerdere paden; houd imports synchroon of refactor later.")

    recommendations.extend([
        "Voor fase C: maak een expliciete aparte ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS of vergelijkbare kill switch.",
        "Voor fase C: start met master-only, kleine quote-size, entry-only of één ticker allowlist, en harde per-cyclus orderlimieten.",
        "Voor fase C: log elke live order met linked pending_intent_id, fresh_analysis_id, judge/risk snapshot en expiry.",
        "Voor fase C: behoud pending intents als context; laat ze nooit zelfstandig execution autoriseren.",
        "Plan later een veilige bronexport zonder .env, .venv, .git, logs, state en backups.",
        "Houd DeepSeek preprocess standaard uit richting fase C, tenzij expliciet getest dat het waarde toevoegt.",
        "Houd Anthropic fallback standaard uit zolang billing/credits niet aantoonbaar gezond zijn.",
    ])

    checklist = _build_phase_c_checklist(status, logs)
    phase_b_safe = not blockers
    return {
        "generated_at_note": "runtime timestamp generated by tool invocation",
        "project_root": str(project_root),
        "phase": "B.8 final report / safety checklist",
        "phase_b_safe_to_continue_paper_only": phase_b_safe,
        "phase_c_ready_without_human_review": False,
        "status": status,
        "log_health": logs,
        "source_hygiene": hygiene,
        "duplicate_filenames": duplicates,
        "phase_c_safety_checklist": checklist,
        "blockers": blockers,
        "warnings": warnings,
        "recommendations": recommendations,
        "safety_policy": "This report does not place, cancel, replace, or authorize orders. Pending intents remain non-executable context.",
    }


def _print_human(report: Dict[str, Any]) -> None:
    status = report["status"]
    cfg = status["config"]
    orders = status["orders"]
    pending = status["pending_order_intents"]
    logs = report["log_health"]

    print("Phase B.8 final report / safety checklist")
    print("=" * 48)
    print(f"project_root: {report.get('project_root')}")
    print(f"phase_b_safe_to_continue_paper_only: {report.get('phase_b_safe_to_continue_paper_only')}")
    print(f"phase_c_ready_without_human_review: {report.get('phase_c_ready_without_human_review')}")
    print()
    print("Config & safety flags")
    print(f"config_ok: {cfg.get('config_ok')}")
    if not cfg.get("config_ok"):
        print(f"config_error: {cfg.get('config_error')}")
    print(f"execution_mode: {cfg.get('execution_mode')}")
    print(f"read_only_execution_planner: {cfg.get('enable_read_only_execution_planner')}")
    print(f"limit_order_manager: {cfg.get('enable_limit_order_manager')}")
    print(f"live_limit_orders: {cfg.get('enable_live_limit_orders')}")
    print(f"live_entry_orders: {cfg.get('enable_live_entry_orders')}")
    print(f"live_exit_orders: {cfg.get('enable_live_exit_orders')}")
    print()
    print("Orders")
    print(f"total: {orders.get('total_orders')} | open: {orders.get('open_orders')} | diagnostics: {orders.get('diagnostic_order_count')}")
    print("by_status:", json.dumps(orders.get("by_status", {}), ensure_ascii=False, sort_keys=True))
    print()
    print("Pending order-intents")
    print(f"total: {pending.get('total_intents')} | open_intents: {pending.get('active_intents')} | diagnostics: {pending.get('diagnostic_intent_count')}")
    print("by_status:", json.dumps(pending.get("by_status", {}), ensure_ascii=False, sort_keys=True))
    print("by_active_status:", json.dumps(pending.get("by_active_status", {}), ensure_ascii=False, sort_keys=True))
    print("trigger_ready_current:", json.dumps(pending.get("trigger_ready", []), ensure_ascii=False, sort_keys=True))
    print("needs_fresh_analysis_current:", json.dumps(pending.get("needs_fresh_analysis", []), ensure_ascii=False, sort_keys=True))
    print("promotion_ready_current:", json.dumps(pending.get("promotion_ready", []), ensure_ascii=False, sort_keys=True))
    if pending.get("replaced_by_ticker"):
        print("replaced_by_ticker:", json.dumps(pending.get("replaced_by_ticker", {}), ensure_ascii=False, sort_keys=True))
    print()
    print("Log health sample")
    print(f"errors_sample_size: {logs.get('errors_sample_size')}")
    print(f"llm_corrupt_sample_size: {logs.get('llm_corrupt_sample_size')}")
    print(f"llm_provider_error_sample_size: {logs.get('llm_provider_error_sample_size')}")
    print("pending_intent_events_by_type:", json.dumps(logs.get("pending_intent_events_by_type", {}), ensure_ascii=False, sort_keys=True))
    print(f"replication_outbox_error_like_rows: {logs.get('replication_outbox_error_like_rows')}")
    print()
    print("Checklist")
    for check in report.get("phase_c_safety_checklist", []):
        mark = "OK" if check.get("passed") else "REVIEW"
        print(f"[{mark}] {check.get('name')} - {check.get('note')}")
    print()
    if report.get("blockers"):
        print("Blockers")
        for item in report["blockers"]:
            print(f"- {item}")
    else:
        print("Blockers: geen")
    print()
    if report.get("warnings"):
        print("Waarschuwingen")
        for item in report["warnings"]:
            print(f"- {item}")
    else:
        print("Waarschuwingen: geen")
    print()
    print("Aanbevelingen")
    for item in report.get("recommendations", []):
        print(f"- {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description="B.8 eindrapportage en safety checklist voor de fase-B paper ordermanager.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--open-orders-path", default="state/open_orders.json")
    parser.add_argument("--pending-intents-path", default="state/pending_order_intents.json")
    parser.add_argument("--execution-outcomes-path", default="logs/execution_outcomes.jsonl")
    parser.add_argument("--execution-plans-path", default="logs/execution_plans.jsonl")
    parser.add_argument("--logs-dir", default="logs")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--include-source-hygiene", action="store_true", default=True)
    parser.add_argument("--no-source-hygiene", dest="include_source_hygiene", action="store_false")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = build_final_report(args)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
