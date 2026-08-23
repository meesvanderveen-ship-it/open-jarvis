from __future__ import annotations

from typing import Any, Dict

from bot.phase_d6_btc_1h_staged_controller import (
    build_binance_btc_1h_reference_report,
    build_btc_1h_staged_controller_plan,
    build_cross_source_btc_1h_gap_diagnostic,
    build_exploratory_backtest_decision_v22_v23,
    build_quality_summary_v22_v23,
    build_resume_status_v3,
    execute_btc_1h_staged_controller,
    safety_flags,
)


PHASE = "D6_btc_1h_staged_controller_v2"


def _retag_common(report: Dict[str, Any], *, report_name: str, status: str) -> Dict[str, Any]:
    out = dict(report)
    out["phase"] = PHASE
    out["report_name"] = report_name
    if str(out.get("status", "")).endswith("_blocked"):
        out["status"] = f"{status}_blocked"
    elif str(out.get("status", "")).endswith("_not_run"):
        out["status"] = f"{status}_not_run"
    else:
        out["status"] = f"{status}_ready"
    return out


def build_btc_1h_staged_controller_plan_v2(**kwargs: Any) -> Dict[str, Any]:
    plan = build_btc_1h_staged_controller_plan(**kwargs)
    for chunk in plan.get("chunks") or []:
        chunk["candidate_output_path"] = str(chunk.get("candidate_output_path", "")).replace("v22-v23", "v24-v25")
        chunk["fetch_plan"]["candidate_output_path"] = str(chunk["fetch_plan"].get("candidate_output_path", "")).replace(
            "v22-v23", "v24-v25"
        )
    return _retag_common(plan, report_name="btc_1h_staged_controller_plan_v2", status="btc_1h_staged_controller_plan_v2")


def execute_btc_1h_staged_controller_v2(**kwargs: Any) -> Dict[str, Any]:
    result = execute_btc_1h_staged_controller(**kwargs)
    return _retag_common(result, report_name="btc_1h_staged_controller_result_v2", status="btc_1h_staged_controller_result_v2")


def build_resume_status_v4(*, plan: Dict[str, Any], result: Dict[str, Any] | None) -> Dict[str, Any]:
    return _retag_common(
        build_resume_status_v3(plan=plan, result=result),
        report_name="btc_1h_staged_resume_status_v4",
        status="btc_1h_staged_resume_status_v4",
    )


def build_binance_btc_1h_reference_report_v3(*, controller_result: Dict[str, Any] | None) -> Dict[str, Any]:
    return _retag_common(
        build_binance_btc_1h_reference_report(controller_result=controller_result),
        report_name="binance_btcusdc_1h_reference_v3",
        status="binance_btcusdc_1h_reference_v3",
    )


def build_cross_source_btc_1h_gap_diagnostic_v2(*, controller_result: Dict[str, Any] | None) -> Dict[str, Any]:
    return _retag_common(
        build_cross_source_btc_1h_gap_diagnostic(controller_result=controller_result),
        report_name="cross_source_btc_1h_gap_diagnostic_v2",
        status="cross_source_btc_1h_gap_diagnostic_v2",
    )


def build_quality_summary_v24_v25(**kwargs: Any) -> Dict[str, Any]:
    quality = build_quality_summary_v22_v23(**kwargs)
    quality["phase"] = PHASE
    quality["report_name"] = "post_btc_1h_staged_quality_summary_v24_v25"
    quality["status"] = "post_btc_1h_staged_quality_summary_v24_v25_ready"
    return quality


def build_exploratory_backtest_decision_v24_v25(*, quality_summary: Dict[str, Any]) -> Dict[str, Any]:
    decision = build_exploratory_backtest_decision_v22_v23(quality_summary=quality_summary)
    decision["phase"] = PHASE
    decision["report_name"] = "exploratory_only_backtest_decision_v24_v25"
    decision["status"] = "exploratory_only_backtest_decision_v24_v25_ready"
    decision["bounded_exploratory_command_plan"] = {
        "allowed": True,
        "scope": "BTC-USDC 1D only-good plumbing plan",
        "run_now": False,
        "normal_backtest": False,
    }
    return decision


__all__ = [
    "PHASE",
    "build_binance_btc_1h_reference_report_v3",
    "build_btc_1h_staged_controller_plan_v2",
    "build_cross_source_btc_1h_gap_diagnostic_v2",
    "build_exploratory_backtest_decision_v24_v25",
    "build_quality_summary_v24_v25",
    "build_resume_status_v4",
    "execute_btc_1h_staged_controller_v2",
    "safety_flags",
]
