from __future__ import annotations

from typing import Any, Dict

from bot.phase_d6_btc_1h_staged_controller_v4 import (
    build_binance_btc_1h_reference_report_v5,
    build_btc_1h_staged_controller_plan_v4,
    build_cross_source_btc_1h_gap_diagnostic_v4,
    build_exploratory_backtest_decision_v28_v29,
    build_quality_summary_v28_v29,
    build_resume_status_v6,
    execute_btc_1h_staged_controller_v4,
    safety_flags,
)


PHASE = "D6_btc_1h_staged_controller_v5"


def _retag(report: Dict[str, Any], *, report_name: str, status: str) -> Dict[str, Any]:
    out = dict(report)
    out["phase"] = PHASE
    out["report_name"] = report_name
    current = str(out.get("status", ""))
    if current.endswith("_blocked"):
        out["status"] = f"{status}_blocked"
    elif current.endswith("_not_run"):
        out["status"] = f"{status}_not_run"
    else:
        out["status"] = f"{status}_ready"
    return out


def build_btc_1h_staged_controller_plan_v5(**kwargs: Any) -> Dict[str, Any]:
    plan = build_btc_1h_staged_controller_plan_v4(**kwargs)
    resume_scope = plan.get("resume_status", {}).get("next_pending_scope")
    for index, chunk in enumerate(plan.get("chunks") or []):
        chunk["candidate_output_path"] = str(chunk.get("candidate_output_path", "")).replace("v28-v29", "v30-v31")
        chunk["fetch_plan"]["candidate_output_path"] = str(chunk["fetch_plan"].get("candidate_output_path", "")).replace(
            "v28-v29", "v30-v31"
        )
        chunk["controller_version"] = "v5"
        chunk["resume_status_before_chunk"] = resume_scope if index == 0 else f"after_previous_chunk_pass:{plan['chunks'][index - 1]['chunk_id']}"
        chunk["allowed_to_attempt"] = index == 0 or "previous_chunk_exact_pass_required"
        chunk["allowed_merge_after_validation_pass"] = True
        chunk["binance_reference_optional"] = True
        chunk["fail_closed_reason_if_stopped"] = ""
    plan["operational_safety"].update(
        {
            "controller_version": "v5",
            "chunk13_chunk14_chunk15_only_if_previous_exact_pass": True,
            "api_rate_limit_clean_required_before_next_chunk": True,
            "candidate_root_under_tmp_required": True,
            "normal_backtest_claim_allowed": False,
        }
    )
    plan["v30_v31_scope"] = {
        "start_resume_scope": resume_scope,
        "planned_chunk_ids": [chunk.get("chunk_id") for chunk in plan.get("chunks") or []],
        "max_chunks_this_sprint": plan.get("max_chunks_this_sprint"),
        "auto_resume_allowed": False,
    }
    return _retag(plan, report_name="btc_1h_staged_controller_plan_v5", status="btc_1h_staged_controller_plan_v5")


def execute_btc_1h_staged_controller_v5(**kwargs: Any) -> Dict[str, Any]:
    result = execute_btc_1h_staged_controller_v4(**kwargs)
    result["controller_version"] = "v5"
    result["fail_closed_reason"] = result.get("stop_reason", "")
    result["api_rate_limit_clean"] = not bool(result.get("stop_reason"))
    result["chunk_batch_review_required_before_next_sprint"] = True
    result["no_auto_resume_after_failure"] = True
    result["normal_backtest_claim_allowed"] = False
    for row in result.get("result_rows") or []:
        if row.get("status") != "completed":
            row["fail_closed_reason_if_stopped"] = result.get("stop_reason", "")
        else:
            row["fail_closed_reason_if_stopped"] = ""
            row["previous_chunk_gate_passed_for_next_chunk"] = True
    return _retag(result, report_name="btc_1h_staged_controller_result_v5", status="btc_1h_staged_controller_result_v5")


def build_resume_status_v7(*, plan: Dict[str, Any], result: Dict[str, Any] | None) -> Dict[str, Any]:
    report = build_resume_status_v6(plan=plan, result=result)
    report["chunk_batch_review_required_before_next_sprint"] = True
    report["no_auto_resume_after_failure"] = True
    return _retag(report, report_name="btc_1h_staged_resume_status_v7", status="btc_1h_staged_resume_status_v7")


def build_binance_btc_1h_reference_report_v6(*, controller_result: Dict[str, Any] | None) -> Dict[str, Any]:
    report = build_binance_btc_1h_reference_report_v5(controller_result=controller_result)
    report["report_name"] = "binance_btcusdc_1h_reference_v6"
    report["provenance"] = {
        "source": "binance_public_klines",
        "role": "secondary_reference_only",
        "max_one_reference_request_per_executed_coinbase_chunk": True,
        "coinbase_cache_mutated": False,
    }
    report["reference_unavailable_retry_policy"] = "no_extra_retry_spam"
    return _retag(report, report_name="binance_btcusdc_1h_reference_v6", status="binance_btcusdc_1h_reference_v6")


def build_cross_source_btc_1h_gap_diagnostic_v5(*, controller_result: Dict[str, Any] | None) -> Dict[str, Any]:
    report = build_cross_source_btc_1h_gap_diagnostic_v4(controller_result=controller_result)
    report["source_contracts"] = {
        "primary": "coinbase_public_candles_research_cache",
        "secondary": "binance_public_klines_reference_only",
        "secondary_can_release_normal_backtests": False,
        "secondary_can_repair_primary_cache": False,
    }
    return _retag(report, report_name="cross_source_btc_1h_gap_diagnostic_v5", status="cross_source_btc_1h_gap_diagnostic_v5")


def build_quality_summary_v30_v31(**kwargs: Any) -> Dict[str, Any]:
    quality = build_quality_summary_v28_v29(**kwargs)
    quality["phase"] = PHASE
    quality["report_name"] = "post_btc_1h_staged_quality_summary_v30_v31"
    quality["status"] = "post_btc_1h_staged_quality_summary_v30_v31_ready"
    quality["btc_4h_known_gap_reference_status"] = {
        "coinbase_raw_gap_still_visible": True,
        "binance_reference_available": True,
        "normal_backtest_released": False,
    }
    return quality


def build_exploratory_backtest_decision_v30_v31(*, quality_summary: Dict[str, Any]) -> Dict[str, Any]:
    decision = build_exploratory_backtest_decision_v28_v29(quality_summary=quality_summary)
    decision["phase"] = PHASE
    decision["report_name"] = "exploratory_only_backtest_decision_v30_v31"
    decision["status"] = "exploratory_only_backtest_decision_v30_v31_ready"
    decision["normal_backtests"] = "deferred"
    decision["bounded_exploratory_command_plan"] = {
        "allowed": True,
        "scope": "BTC-USDC 1D only-good tiny plumbing plan",
        "run_now": False,
        "normal_backtest": False,
        "creates_parameter_evidence": False,
    }
    decision["parameter_evidence_created"] = False
    return decision


__all__ = [
    "PHASE",
    "build_binance_btc_1h_reference_report_v6",
    "build_btc_1h_staged_controller_plan_v5",
    "build_cross_source_btc_1h_gap_diagnostic_v5",
    "build_exploratory_backtest_decision_v30_v31",
    "build_quality_summary_v30_v31",
    "build_resume_status_v7",
    "execute_btc_1h_staged_controller_v5",
    "safety_flags",
]
