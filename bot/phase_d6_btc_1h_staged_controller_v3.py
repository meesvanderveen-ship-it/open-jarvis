from __future__ import annotations

from typing import Any, Dict

from bot.phase_d6_btc_1h_staged_controller_v2 import (
    build_binance_btc_1h_reference_report_v3,
    build_btc_1h_staged_controller_plan_v2,
    build_cross_source_btc_1h_gap_diagnostic_v2,
    build_exploratory_backtest_decision_v24_v25,
    build_quality_summary_v24_v25,
    build_resume_status_v4,
    execute_btc_1h_staged_controller_v2,
    safety_flags,
)


PHASE = "D6_btc_1h_staged_controller_v3"


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


def build_btc_1h_staged_controller_plan_v3(**kwargs: Any) -> Dict[str, Any]:
    plan = build_btc_1h_staged_controller_plan_v2(**kwargs)
    for chunk in plan.get("chunks") or []:
        chunk["candidate_output_path"] = str(chunk.get("candidate_output_path", "")).replace("v24-v25", "v26-v27")
        chunk["fetch_plan"]["candidate_output_path"] = str(chunk["fetch_plan"].get("candidate_output_path", "")).replace(
            "v24-v25", "v26-v27"
        )
        chunk["fail_closed_stop_reasons"] = [
            "api_error",
            "zero_candle_response",
            "partial_candidate",
            "validation_failure",
            "unexpected_overlap",
            "source_mismatch",
            "rate_limit_condition",
            "safety_drift",
        ]
        chunk["binance_reference_optional"] = True
    plan["operational_safety"] = {
        "max_chunks_this_sprint": plan.get("max_chunks_this_sprint"),
        "no_parallel_fetch": True,
        "auto_resume_allowed": False,
        "stop_after_first_failure": True,
        "normal_backtest_claim_allowed": False,
    }
    return _retag(plan, report_name="btc_1h_staged_controller_plan_v3", status="btc_1h_staged_controller_plan_v3")


def execute_btc_1h_staged_controller_v3(**kwargs: Any) -> Dict[str, Any]:
    result = execute_btc_1h_staged_controller_v2(**kwargs)
    result["fail_closed_reason"] = result.get("stop_reason", "")
    result["no_auto_resume_after_failure"] = True
    result["normal_backtest_claim_allowed"] = False
    return _retag(result, report_name="btc_1h_staged_controller_result_v3", status="btc_1h_staged_controller_result_v3")


def build_resume_status_v5(*, plan: Dict[str, Any], result: Dict[str, Any] | None) -> Dict[str, Any]:
    return _retag(build_resume_status_v4(plan=plan, result=result), report_name="btc_1h_staged_resume_status_v5", status="btc_1h_staged_resume_status_v5")


def build_binance_btc_1h_reference_report_v4(*, controller_result: Dict[str, Any] | None) -> Dict[str, Any]:
    report = build_binance_btc_1h_reference_report_v3(controller_result=controller_result)
    report["spam_prevention"] = {"max_one_reference_request_per_executed_chunk": True, "extra_retry_spam_allowed": False}
    return _retag(report, report_name="binance_btcusdc_1h_reference_v4", status="binance_btcusdc_1h_reference_v4")


def build_cross_source_btc_1h_gap_diagnostic_v3(*, controller_result: Dict[str, Any] | None) -> Dict[str, Any]:
    return _retag(build_cross_source_btc_1h_gap_diagnostic_v2(controller_result=controller_result), report_name="cross_source_btc_1h_gap_diagnostic_v3", status="cross_source_btc_1h_gap_diagnostic_v3")


def build_quality_summary_v26_v27(**kwargs: Any) -> Dict[str, Any]:
    quality = build_quality_summary_v24_v25(**kwargs)
    quality["phase"] = PHASE
    quality["report_name"] = "post_btc_1h_staged_quality_summary_v26_v27"
    quality["status"] = "post_btc_1h_staged_quality_summary_v26_v27_ready"
    return quality


def build_exploratory_backtest_decision_v26_v27(*, quality_summary: Dict[str, Any]) -> Dict[str, Any]:
    decision = build_exploratory_backtest_decision_v24_v25(quality_summary=quality_summary)
    decision["phase"] = PHASE
    decision["report_name"] = "exploratory_only_backtest_decision_v26_v27"
    decision["status"] = "exploratory_only_backtest_decision_v26_v27_ready"
    decision["normal_backtests"] = "deferred"
    decision["parameter_evidence_created"] = False
    return decision


__all__ = [
    "PHASE",
    "build_binance_btc_1h_reference_report_v4",
    "build_btc_1h_staged_controller_plan_v3",
    "build_cross_source_btc_1h_gap_diagnostic_v3",
    "build_exploratory_backtest_decision_v26_v27",
    "build_quality_summary_v26_v27",
    "build_resume_status_v5",
    "execute_btc_1h_staged_controller_v3",
    "safety_flags",
]
