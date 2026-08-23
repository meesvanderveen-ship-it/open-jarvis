from __future__ import annotations

from typing import Any, Dict

from bot.phase_d6_btc_1h_staged_controller_v3 import (
    build_binance_btc_1h_reference_report_v4,
    build_btc_1h_staged_controller_plan_v3,
    build_cross_source_btc_1h_gap_diagnostic_v3,
    build_exploratory_backtest_decision_v26_v27,
    build_quality_summary_v26_v27,
    build_resume_status_v5,
    execute_btc_1h_staged_controller_v3,
    safety_flags,
)


PHASE = "D6_btc_1h_staged_controller_v4"


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


def build_btc_1h_staged_controller_plan_v4(**kwargs: Any) -> Dict[str, Any]:
    plan = build_btc_1h_staged_controller_plan_v3(**kwargs)
    for chunk in plan.get("chunks") or []:
        chunk["candidate_output_path"] = str(chunk.get("candidate_output_path", "")).replace("v26-v27", "v28-v29")
        chunk["fetch_plan"]["candidate_output_path"] = str(chunk["fetch_plan"].get("candidate_output_path", "")).replace(
            "v26-v27", "v28-v29"
        )
        chunk["controller_version"] = "v4"
        chunk["requires_exact_validation_before_merge"] = True
    plan["operational_safety"]["candidate_root_under_tmp_required"] = True
    plan["operational_safety"]["merge_only_after_candidate_validation_pass"] = True
    return _retag(plan, report_name="btc_1h_staged_controller_plan_v4", status="btc_1h_staged_controller_plan_v4")


def execute_btc_1h_staged_controller_v4(**kwargs: Any) -> Dict[str, Any]:
    result = execute_btc_1h_staged_controller_v3(**kwargs)
    result["candidate_root_under_tmp_required"] = True
    result["merge_only_after_candidate_validation_pass"] = True
    result["no_auto_resume_after_failure"] = True
    result["normal_backtest_claim_allowed"] = False
    return _retag(result, report_name="btc_1h_staged_controller_result_v4", status="btc_1h_staged_controller_result_v4")


def build_resume_status_v6(*, plan: Dict[str, Any], result: Dict[str, Any] | None) -> Dict[str, Any]:
    return _retag(build_resume_status_v5(plan=plan, result=result), report_name="btc_1h_staged_resume_status_v6", status="btc_1h_staged_resume_status_v6")


def build_binance_btc_1h_reference_report_v5(*, controller_result: Dict[str, Any] | None) -> Dict[str, Any]:
    report = build_binance_btc_1h_reference_report_v4(controller_result=controller_result)
    report["optional_reference_diagnostic"] = True
    report["reference_defer_reason"] = "" if controller_result else "no_fetch_result_available"
    return _retag(report, report_name="binance_btcusdc_1h_reference_v5", status="binance_btcusdc_1h_reference_v5")


def build_cross_source_btc_1h_gap_diagnostic_v4(*, controller_result: Dict[str, Any] | None) -> Dict[str, Any]:
    report = build_cross_source_btc_1h_gap_diagnostic_v3(controller_result=controller_result)
    report["coinbase_primary_execution_market_dataset"] = True
    report["binance_secondary_reference_only"] = True
    return _retag(report, report_name="cross_source_btc_1h_gap_diagnostic_v4", status="cross_source_btc_1h_gap_diagnostic_v4")


def build_quality_summary_v28_v29(**kwargs: Any) -> Dict[str, Any]:
    quality = build_quality_summary_v26_v27(**kwargs)
    quality["phase"] = PHASE
    quality["report_name"] = "post_btc_1h_staged_quality_summary_v28_v29"
    quality["status"] = "post_btc_1h_staged_quality_summary_v28_v29_ready"
    return quality


def build_exploratory_backtest_decision_v28_v29(*, quality_summary: Dict[str, Any]) -> Dict[str, Any]:
    decision = build_exploratory_backtest_decision_v26_v27(quality_summary=quality_summary)
    decision["phase"] = PHASE
    decision["report_name"] = "exploratory_only_backtest_decision_v28_v29"
    decision["status"] = "exploratory_only_backtest_decision_v28_v29_ready"
    decision["normal_backtests"] = "deferred"
    decision["parameter_evidence_created"] = False
    decision["normal_backtest_release_blocked_until_primary_coinbase_quality_passes"] = True
    return decision


__all__ = [
    "PHASE",
    "build_binance_btc_1h_reference_report_v5",
    "build_btc_1h_staged_controller_plan_v4",
    "build_cross_source_btc_1h_gap_diagnostic_v4",
    "build_exploratory_backtest_decision_v28_v29",
    "build_quality_summary_v28_v29",
    "build_resume_status_v6",
    "execute_btc_1h_staged_controller_v4",
    "safety_flags",
]
