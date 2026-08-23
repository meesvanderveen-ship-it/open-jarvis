from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Sequence

from bot.phase_d6_btc_1h_staged_controller import BTC_1H_CANDLES, _detect_first_gap, _iso_from_ts, safety_flags
from bot.phase_d6_btc_1h_staged_controller_v6 import (
    build_btc_1h_staged_controller_plan_v6,
    build_quality_summary_v32_v33,
    build_resume_status_v8,
    execute_btc_1h_staged_controller_v6,
)
from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_metrics import now_iso


PHASE = "D6_btc_1h_server_downloader_v1"
MAX_CHUNKS_PER_PHASE = 3
MAX_CHUNKS_PER_RUN = 30
DEFAULT_CANDIDATE_ROOT = "/tmp/d6_btc_1h_server_downloader_v1"


def _load_report_content(path: str | Path) -> Dict[str, Any]:
    loaded = json.loads(assert_research_path(path).read_text(encoding="utf-8"))
    content = loaded.get("content") if isinstance(loaded, dict) else None
    return dict(content) if isinstance(content, dict) else dict(loaded)


def _chunk_number(scope: str) -> int:
    text = str(scope)
    if "chunk" not in text:
        raise ValueError("btc_1h_server_downloader_scope_missing_chunk")
    return int(text.rsplit("chunk", 1)[1].split("_", 1)[0].split(":", 1)[0])


def _completed_chunks_until(chunk_number_exclusive: int) -> List[str]:
    return [f"BTCUSDC-1H-gap01:chunk{idx}" for idx in range(int(chunk_number_exclusive))]


def normalize_resume_for_controller(resume: Dict[str, Any]) -> Dict[str, Any]:
    next_scope = resume.get("next_pending_scope") or resume.get("next_scope")
    if not next_scope:
        raise ValueError("btc_1h_server_downloader_resume_missing_next_scope")
    next_chunk = _chunk_number(str(next_scope))
    completed = list(resume.get("completed_pilot_chunks") or [])
    if not completed:
        completed = list(resume.get("previous_completed_chunks") or []) + list(resume.get("new_completed_chunks") or [])
    if len(completed) < next_chunk:
        completed = _completed_chunks_until(next_chunk)
    normalized = dict(resume)
    normalized.update(
        {
            "next_scope": f"BTCUSDC-1H-gap01:chunk{next_chunk}_or_review",
            "next_pending_scope": f"BTCUSDC-1H-gap01:chunk{next_chunk}_or_review",
            "completed_pilot_chunks": completed,
            "previous_completed_chunks": completed,
            "new_completed_chunks": [],
            "auto_resume_allowed": False,
            "requires_operator_review_before_next_chunk": True,
        }
    )
    return normalized


def _write_tmp_resume(resume: Dict[str, Any], candidate_root: str | Path, phase_index: int) -> Path:
    root = assert_research_path(candidate_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"server-downloader-resume-phase-{phase_index:02d}.json"
    path.write_text(json.dumps({"content": resume}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _cache_count(path: str | Path = BTC_1H_CANDLES) -> int:
    rows = json.loads(assert_research_path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        return 0
    return len({int(row["start"]) for row in rows if isinstance(row, dict) and "start" in row})


def _safety_command(command: Sequence[str], *, cwd: str | Path) -> Dict[str, Any]:
    result = subprocess.run(list(command), cwd=str(cwd), text=True, capture_output=True, check=False)
    return {
        "command": list(command),
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }


def run_final_style_safety_checks(*, cwd: str | Path = ".") -> Dict[str, Any]:
    commands = [
        ["python3", "tools/show_open_orders.py", "--open-only", "--json", "--limit", "20"],
        ["python3", "tools/show_function_preservation_audit.py", "--fail-on-review"],
        ["python3", "tools/show_phase_d3_controlled_live_exits.py", "--ticker", "BTC-USDC", "--json"],
        ["sha256sum", "state/open_orders.json", "state/positions.json"],
    ]
    results = [_safety_command(command, cwd=cwd) for command in commands]
    return {
        "generated_at": now_iso(),
        "status": "safety_checks_pass" if all(row["returncode"] == 0 for row in results) else "safety_checks_blocked",
        "results": results,
        **safety_flags(),
    }


def build_server_download_plan(
    *,
    resume_status_path: str | Path,
    candidate_root: str | Path = DEFAULT_CANDIDATE_ROOT,
    max_chunks: int = MAX_CHUNKS_PER_RUN,
    phase_size: int = MAX_CHUNKS_PER_PHASE,
    existing_path: str | Path = BTC_1H_CANDLES,
    cooldown_seconds: float = 2.0,
    checkpoint_interval_chunks: int = 9,
    binance_reference: bool = False,
) -> Dict[str, Any]:
    if int(phase_size) <= 0 or int(phase_size) > MAX_CHUNKS_PER_PHASE:
        raise ValueError("btc_1h_server_downloader_phase_size_out_of_bounds")
    if int(max_chunks) <= 0 or int(max_chunks) > MAX_CHUNKS_PER_RUN:
        raise ValueError("btc_1h_server_downloader_max_chunks_out_of_bounds")
    resume = normalize_resume_for_controller(_load_report_content(resume_status_path))
    first_gap = _detect_first_gap(candles_path=existing_path)
    next_chunk = _chunk_number(str(resume["next_pending_scope"]))
    remaining = int(first_gap.get("missing_candle_count") or 0)
    planned_total = min(int(max_chunks), (remaining + 349) // 350 if remaining else 0)
    phases: List[Dict[str, Any]] = []
    for offset in range(0, planned_total, int(phase_size)):
        count = min(int(phase_size), planned_total - offset)
        phase_number = len(phases) + 1
        phase_start_chunk = next_chunk + offset
        phases.append(
            {
                "phase_index": phase_number,
                "phase_id": f"phase_{phase_number:02d}",
                "chunk_start": phase_start_chunk,
                "chunk_end_inclusive": phase_start_chunk + count - 1,
                "max_chunks": count,
                "candidate_root": str(assert_research_path(candidate_root) / f"phase_{phase_number:02d}"),
                "requires_previous_phase_clean": phase_number > 1,
                "status": "planned",
            }
        )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "btc_1h_server_download_plan_v1",
        "status": "btc_1h_server_download_plan_v1_ready" if phases else "btc_1h_server_download_plan_v1_no_gap",
        "start_scope": resume["next_pending_scope"],
        "normalized_resume": resume,
        "candidate_root": str(assert_research_path(candidate_root)),
        "max_chunks": int(max_chunks),
        "phase_size": int(phase_size),
        "checkpoint_interval_chunks": int(checkpoint_interval_chunks),
        "cooldown_seconds": float(cooldown_seconds),
        "binance_reference_enabled": bool(binance_reference),
        "first_gap": first_gap,
        "cache_count_before": _cache_count(existing_path),
        "planned_chunk_count": planned_total,
        "planned_phase_count": len(phases),
        "phases": phases,
        "stop_conditions": [
            "partial_candidate",
            "zero_candle_response",
            "coinbase_api_error",
            "repeated_network_error",
            "rate_limit_condition",
            "validation_failure",
            "unexpected_overlap",
            "source_mismatch",
            "write_or_path_issue",
            "safety_drift",
            "unexpected_open_order",
            "audit_not_ok_observe_only",
        ],
        **safety_flags(),
    }


def _phase_clean(result: Dict[str, Any], expected_count: int) -> bool:
    if result.get("status") != "btc_1h_staged_controller_result_v6_ready":
        return False
    if result.get("stop_reason"):
        return False
    if len(result.get("completed_chunk_ids") or []) != int(expected_count):
        return False
    for row in result.get("result_rows") or []:
        validation = row.get("candidate_validation") or {}
        if row.get("status") != "completed" or validation.get("validator_pass") is not True or row.get("merge_executed") is not True:
            return False
    return True


def execute_server_download(
    *,
    plan: Dict[str, Any],
    coinbase_client: Any,
    cwd: str | Path = ".",
    merge: bool = True,
    binance_reference: bool | None = None,
    cooldown: Callable[[float], None] = time.sleep,
    run_safety_checks: Callable[..., Dict[str, Any]] = run_final_style_safety_checks,
) -> Dict[str, Any]:
    if coinbase_client is None:
        raise ValueError("btc_1h_server_downloader_requires_read_only_coinbase_client")
    if plan.get("max_chunks", 0) > MAX_CHUNKS_PER_RUN:
        raise ValueError("btc_1h_server_downloader_refuses_over_max_chunks")
    current_resume = dict(plan["normalized_resume"])
    phase_summaries: List[Dict[str, Any]] = []
    checkpoint_summaries: List[Dict[str, Any]] = []
    completed: List[str] = []
    stop_reason = ""
    cache_before = int(plan.get("cache_count_before") or _cache_count())
    use_binance = bool(plan.get("binance_reference_enabled") if binance_reference is None else binance_reference)
    for phase_spec in plan.get("phases") or []:
        if phase_spec.get("requires_previous_phase_clean") and (not phase_summaries or phase_summaries[-1].get("phase_clean") is not True):
            stop_reason = "previous_phase_not_clean"
            break
        resume_path = _write_tmp_resume(current_resume, phase_spec["candidate_root"], int(phase_spec["phase_index"]))
        phase_plan = build_btc_1h_staged_controller_plan_v6(
            resume_status_path=resume_path,
            candidate_root=phase_spec["candidate_root"],
            max_chunks=int(phase_spec["max_chunks"]),
        )
        phase_result = execute_btc_1h_staged_controller_v6(
            plan=phase_plan,
            coinbase_client=coinbase_client,
            max_execute_chunks=int(phase_spec["max_chunks"]),
            merge=merge,
            binance_reference=use_binance,
        )
        phase_resume = build_resume_status_v8(plan=phase_plan, result=phase_result)
        quality = build_quality_summary_v32_v33()
        clean = _phase_clean(phase_result, int(phase_spec["max_chunks"]))
        completed.extend(phase_result.get("completed_chunk_ids") or [])
        first_gap = _detect_first_gap()
        phase_summary = {
            **phase_spec,
            "status": "completed_clean" if clean else "blocked",
            "phase_clean": clean,
            "planned_chunks": [row.get("chunk_id") for row in phase_plan.get("chunks") or []],
            "completed_chunks": list(phase_result.get("completed_chunk_ids") or []),
            "stop_reason": phase_result.get("stop_reason", ""),
            "api_summary": {
                "coinbase_public_market_data_call_count": phase_result.get("coinbase_public_market_data_call_count"),
                "rate_limit_clean": not bool(phase_result.get("stop_reason")),
                "binance_reference_enabled": use_binance,
            },
            "validation_summary": [
                {
                    "chunk_id": row.get("chunk_id"),
                    "status": row.get("status"),
                    "validator_pass": (row.get("candidate_validation") or {}).get("validator_pass"),
                    "validation_status": (row.get("candidate_validation") or {}).get("status"),
                    "expected_candle_count": row.get("expected_candle_count"),
                }
                for row in phase_result.get("result_rows") or []
            ],
            "merge_summary": [
                {"chunk_id": row.get("chunk_id"), "merge_executed": row.get("merge_executed")}
                for row in phase_result.get("result_rows") or []
            ],
            "resume_status": {
                "next_pending_scope": phase_resume.get("next_pending_scope"),
                "completed_chunk_count_this_sprint": phase_resume.get("completed_chunk_count_this_sprint"),
                "auto_resume_allowed": phase_resume.get("auto_resume_allowed"),
            },
            "quality_quick_refresh": {
                "global_counters": quality.get("global_counters"),
                "first_gap": first_gap,
                "cache_count": _cache_count(),
            },
            "go_decision": "continue" if clean else "stop_fail_closed",
        }
        phase_summaries.append(phase_summary)
        current_resume = normalize_resume_for_controller(phase_resume)
        if not clean:
            stop_reason = phase_result.get("stop_reason") or "phase_not_clean"
            break
        if len(completed) % int(plan.get("checkpoint_interval_chunks") or 9) == 0:
            safety = run_safety_checks(cwd=cwd)
            checkpoint_summaries.append(
                {
                    "after_completed_chunk_count": len(completed),
                    "safety_status": safety.get("status"),
                    "safety_summary": safety,
                    "go_decision": "continue" if safety.get("status") == "safety_checks_pass" else "stop_fail_closed",
                }
            )
            if safety.get("status") != "safety_checks_pass":
                stop_reason = "safety_drift_after_checkpoint"
                break
        cooldown(float(plan.get("cooldown_seconds") or 0.0))
    final_gap = _detect_first_gap()
    cache_after = _cache_count()
    gap_closed = not bool(final_gap.get("gap_start"))
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "btc_1h_server_download_result_v1",
        "status": "btc_1h_server_download_result_v1_ready" if not stop_reason else "btc_1h_server_download_result_v1_blocked",
        "start_scope": plan.get("start_scope"),
        "next_pending_scope": current_resume.get("next_pending_scope"),
        "planned_chunk_count": plan.get("planned_chunk_count"),
        "completed_chunk_count": len(completed),
        "completed_chunks": completed,
        "phase_summaries": phase_summaries,
        "checkpoint_summaries": checkpoint_summaries,
        "cache_count_before": cache_before,
        "cache_count_after": cache_after,
        "added_candles": cache_after - cache_before,
        "final_gap": final_gap,
        "gap_closed": gap_closed,
        "stop_reason": stop_reason,
        "max_chunks_reached": len(completed) >= int(plan.get("max_chunks") or 0),
        "binance_reference_enabled": use_binance,
        **safety_flags(),
    }


def build_progress_report(*, plan: Dict[str, Any], result: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "btc_1h_server_download_progress_v1",
        "status": "btc_1h_server_download_progress_v1_ready",
        "start_scope": plan.get("start_scope"),
        "planned_chunk_count": plan.get("planned_chunk_count"),
        "completed_chunk_count": (result or {}).get("completed_chunk_count", 0),
        "completed_chunks": list((result or {}).get("completed_chunks") or []),
        "phase_summaries": list((result or {}).get("phase_summaries") or []),
        "next_pending_scope": (result or {}).get("next_pending_scope", plan.get("start_scope")),
        **safety_flags(),
    }


def build_resume_status_v11(*, plan: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    next_scope = result.get("next_pending_scope") or plan.get("start_scope")
    next_chunk = _chunk_number(str(next_scope)) if next_scope else 0
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "btc_1h_staged_resume_status_v11",
        "status": "btc_1h_staged_resume_status_v11_ready",
        "next_scope": next_scope,
        "next_pending_scope": next_scope,
        "completed_chunks_total": next_chunk,
        "completed_pilot_chunks": _completed_chunks_until(next_chunk),
        "new_completed_chunks": list(result.get("completed_chunks") or []),
        "completed_chunks_this_run": list(result.get("completed_chunks") or []),
        "auto_resume_allowed": False,
        "gap_closed": bool(result.get("gap_closed")),
        "cache_count_before": result.get("cache_count_before"),
        "cache_count_after": result.get("cache_count_after"),
        "remaining_gap_start_iso": _iso_from_ts(result["final_gap"]["gap_start"]) if result.get("final_gap", {}).get("gap_start") else None,
        "remaining_gap_end_exclusive_iso": _iso_from_ts(result["final_gap"]["gap_end_exclusive"]) if result.get("final_gap", {}).get("gap_end_exclusive") else None,
        "remaining_missing_candles_estimated": result.get("final_gap", {}).get("missing_candle_count", 0),
        "stop_reason": result.get("stop_reason", ""),
        **safety_flags(),
    }


def build_quality_summary_v1(*, result: Dict[str, Any]) -> Dict[str, Any]:
    quality = build_quality_summary_v32_v33()
    quality.update(
        {
            "phase": PHASE,
            "report_name": "post_btc_1h_server_download_quality_summary_v1",
            "status": "post_btc_1h_server_download_quality_summary_v1_ready",
            "server_download_progress": {
                "completed_chunk_count": result.get("completed_chunk_count"),
                "cache_count_before": result.get("cache_count_before"),
                "cache_count_after": result.get("cache_count_after"),
                "added_candles": result.get("added_candles"),
                "gap_closed": result.get("gap_closed"),
                "final_gap": result.get("final_gap"),
            },
            "normal_backtests": "deferred_primary_coinbase_quality_not_confirmed_good",
            "btc_usdc_only_24h_readiness": "not_ready",
        }
    )
    for row in quality.get("rows", []):
        if row.get("product_id") == "BTC-USDC" and row.get("timeframe") == "1H":
            row["candle_count"] = result.get("cache_count_after")
    return quality


def build_24h_readiness_v38(*, result: Dict[str, Any], quality: Dict[str, Any], resume: Dict[str, Any]) -> Dict[str, Any]:
    quality_counters = dict(quality.get("global_counters") or {})
    ready = bool(result.get("gap_closed")) and quality_counters.get("poor_count", 1) == 0 and quality_counters.get("warning_count", 1) == 0
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "24h_readiness_master_packet_v38_server_download",
        "status": "24h_readiness_v38_server_download_not_ready",
        "btc_usdc_only_24h_readiness": {
            "closer_than_v36_v37": bool(result.get("completed_chunk_count")),
            "ready_for_24h_live_run": False,
            "primary_coinbase_1h_gap_closed": bool(result.get("gap_closed")),
            "cache_count_after": result.get("cache_count_after"),
            "next_btc_1h_scope": resume.get("next_pending_scope"),
            "remaining_gap": result.get("final_gap"),
            "remaining_blockers": [
                "primary_coinbase_dataset_quality_must_be_rechecked_after_download",
                "btc_usdc_4h_coinbase_raw_gap_still_visible",
                "normal_backtests_deferred",
                "future_live_test_ack_missing",
            ],
        },
        "dataset_quality": quality_counters,
        "normal_backtests": "deferred",
        "live_24h_ready_after_this_report": ready and False,
        "required_future_acks": [
            "fresh_coinbase_read_preflight_ack",
            "explicit_24h_live_test_start_ack_after_fresh_preflight_pass",
            "separate_lifecycle_apply_ack_if_any_live_order_fills",
        ],
        "next_largest_step": "rerun_dataset_quality_and_readiness_after_gap_download_or_continue_from_resume_scope",
        **safety_flags(),
    }


__all__ = [
    "MAX_CHUNKS_PER_PHASE",
    "MAX_CHUNKS_PER_RUN",
    "PHASE",
    "build_24h_readiness_v38",
    "build_progress_report",
    "build_quality_summary_v1",
    "build_resume_status_v11",
    "build_server_download_plan",
    "execute_server_download",
    "normalize_resume_for_controller",
    "run_final_style_safety_checks",
]
