#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


DEFAULT_JSON_OUT = Path("reports/audits/decision-pipeline-v2-latest.json")
DEFAULT_MD_OUT = Path("reports/audits/decision-pipeline-v2-latest.md")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_jsonl(path: Path, *, limit: int = 2000) -> List[Dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _parse_ts(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _nested(row: Dict[str, Any], *keys: str) -> Any:
    value: Any = row
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _last_by_ticker(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or _nested(row, "feature_pack", "ticker") or "").strip().upper()
        if ticker:
            out[ticker] = row
    return out


def _reason_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _first_nonempty(*values: Any, default: str = "") -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _objective_score(trade_plan: Dict[str, Any], row: Dict[str, Any]) -> Any:
    for key in ("objective_score", "diagnostic_objective_score"):
        if key in trade_plan:
            return trade_plan.get(key)
    return _nested(row, "feature_pack", "decision_context", "objective_score")


def _planner_called(trade_plan: Dict[str, Any]) -> bool:
    source = str(trade_plan.get("source") or "")
    return bool(source.startswith("openai:") or source == "llm_trade_planner")


def _judge_called(judge: Dict[str, Any]) -> bool:
    reasons = " ".join(_reason_list(judge.get("reasons"))).lower()
    strategy = str(judge.get("strategy") or "").lower()
    return "judge_provider=" in reasons or ("mini_analysis_screened_no_expensive_judge" not in strategy and "entry_gate_" not in strategy)


def _missing_condition(row: Dict[str, Any], execution: Dict[str, Any]) -> str:
    judge = row.get("judge") if isinstance(row.get("judge"), dict) else {}
    trade_plan = row.get("trade_plan") if isinstance(row.get("trade_plan"), dict) else {}
    reasons = _reason_list(judge.get("reasons")) + _reason_list(trade_plan.get("missing_trigger_reasons"))
    hard_rejects = _reason_list(execution.get("hard_rejects"))
    if hard_rejects:
        return hard_rejects[0]
    if str(judge.get("decision") or "").lower() != "approve_trade":
        return "final_judge_approval_missing"
    if str(judge.get("side") or "").upper() != "BUY":
        return "final_judge_buy_side_missing"
    if str(trade_plan.get("plan_action") or "no_plan").lower() == "no_plan":
        return str(trade_plan.get("reason") or "planner_no_plan")
    return "all_entry_guards_not_proven_green"


def build_decision_pipeline_v2_audit(*, root: str | Path = ".") -> Dict[str, Any]:
    project_root = Path(root)
    analysis_rows = _load_jsonl(project_root / "logs/analysis.jsonl")
    execution_rows = _load_jsonl(project_root / "logs/execution.jsonl")
    cycle_rows = _load_jsonl(project_root / "logs/cycle_summary.jsonl", limit=200)
    lifecycle_rows = _load_jsonl(project_root / "logs/phase_c43_lifecycle_service.jsonl", limit=200)
    latest_cycle_ts = _parse_ts((cycle_rows[-1] if cycle_rows else {}).get("generated_at"))
    if latest_cycle_ts is not None:
        window_start = latest_cycle_ts - timedelta(minutes=20)
        analysis_rows = [
            row for row in analysis_rows
            if (ts := _parse_ts(row.get("generated_at"))) is not None and window_start <= ts <= latest_cycle_ts + timedelta(minutes=2)
        ]
        execution_rows = [
            row for row in execution_rows
            if (ts := _parse_ts(row.get("generated_at"))) is not None and window_start <= ts <= latest_cycle_ts + timedelta(minutes=2)
        ]
    latest_analysis = _last_by_ticker(analysis_rows)
    latest_execution = _last_by_ticker(execution_rows)
    latest_lifecycle = lifecycle_rows[-1] if lifecycle_rows else {}
    lifecycle_summary = latest_lifecycle.get("summary") if isinstance(latest_lifecycle.get("summary"), dict) else {}

    tickers = sorted(set(latest_analysis) | (set(latest_execution) if latest_cycle_ts is None else set()))
    rows: List[Dict[str, Any]] = []
    for ticker in tickers:
        row = latest_analysis.get(ticker, {})
        execution = latest_execution.get(ticker, {})
        feature_pack = row.get("feature_pack") if isinstance(row.get("feature_pack"), dict) else {}
        entry_gate = row.get("entry_gate") if isinstance(row.get("entry_gate"), dict) else feature_pack.get("entry_gate", {})
        judge = row.get("judge") if isinstance(row.get("judge"), dict) else execution.get("judge", {})
        trade_plan = row.get("trade_plan") if isinstance(row.get("trade_plan"), dict) else {}
        hard_rejects = _reason_list(execution.get("hard_rejects"))
        planner_called = _planner_called(trade_plan)
        expensive_judge_called = _judge_called(judge if isinstance(judge, dict) else {})
        final_decision = _first_nonempty(
            (judge or {}).get("decision") if isinstance(judge, dict) else "",
            execution.get("status"),
            default="unknown",
        )
        live_entry = row.get("phase_c43_live_entry") if isinstance(row.get("phase_c43_live_entry"), dict) else {}
        why_wait = _first_nonempty(
            execution.get("reason"),
            (trade_plan or {}).get("reason") if isinstance(trade_plan, dict) else "",
            "; ".join(_reason_list((judge or {}).get("reasons") if isinstance(judge, dict) else [])),
            default="not_available",
        )
        item = {
            "ticker": ticker,
            "prefilter_score": _nested(feature_pack, "prefilter", "score")
            or _nested(feature_pack, "decision_context", "prefilter_score")
            or entry_gate.get("prefilter_score"),
            "prefilter_result": _first_nonempty(_nested(feature_pack, "prefilter", "prefilter_decision"), entry_gate.get("decision"), default="unknown"),
            "analysis_result": _first_nonempty(row.get("status"), final_decision, default="unknown"),
            "entry_gate_decision": _first_nonempty(entry_gate.get("decision"), (judge or {}).get("strategy") if isinstance(judge, dict) else "", default="unknown"),
            "gate_confidence": entry_gate.get("confidence") or (judge or {}).get("confidence") if isinstance(judge, dict) else None,
            "setup_type": _first_nonempty((judge or {}).get("setup_type") if isinstance(judge, dict) else "", entry_gate.get("setup_type"), default="unclear"),
            "selected_for_full_analysis": str(entry_gate.get("decision") or "").lower() in {"analyze", "priority_analyze"},
            "planner_called": planner_called,
            "planner_skip_reason": "" if planner_called else _first_nonempty((trade_plan or {}).get("reason"), default="planner_skipped_or_no_plan"),
            "diagnostic_plan_action": _first_nonempty((trade_plan or {}).get("plan_action"), default="diagnostic_no_plan"),
            "objective_score": _objective_score(trade_plan if isinstance(trade_plan, dict) else {}, row),
            "missing_trigger_reasons": _reason_list((trade_plan or {}).get("missing_trigger_reasons") if isinstance(trade_plan, dict) else []),
            "expensive_judge_called": expensive_judge_called,
            "judge_skip_reason": "" if expensive_judge_called else _first_nonempty("; ".join(_reason_list((judge or {}).get("reasons") if isinstance(judge, dict) else [])), default="judge_skipped_or_entry_gate_wait"),
            "final_decision": final_decision,
            "hard_risk_status": "green" if not hard_rejects and final_decision == "approve_trade" else ("not_reached" if final_decision != "approve_trade" else "blocked"),
            "hard_rejects": hard_rejects,
            "phase_c43_status": _first_nonempty(live_entry.get("status"), default="not_reached"),
            "d2_d3_status": "connected_noop" if lifecycle_summary.get("local_c43_open_orders_seen") == 0 and lifecycle_summary.get("local_d3_open_exit_orders_seen") == 0 else "see_lifecycle_summary",
            "c43_status": _first_nonempty(live_entry.get("status"), default="not_reached"),
            "execution_allowed": bool(final_decision == "approve_trade" and not hard_rejects),
            "live_bridge_attempted": bool(live_entry),
            "live_order_submitted": bool(live_entry.get("live_order_submitted") or execution.get("executed")),
            "why_wait": why_wait,
            "next_condition_to_watch": _missing_condition(row, execution),
        }
        rows.append(item)

    return {
        "phase": "decision_pipeline_v2_audit",
        "generated_at": _now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "service_touched": False,
        "tickers": rows,
        "summary": {
            "ticker_count": len(rows),
            "cycle_generated_at": latest_cycle_ts.isoformat().replace("+00:00", "Z") if latest_cycle_ts else "",
            "approve_trade": sum(1 for row in rows if row["final_decision"] == "approve_trade"),
            "wait_or_not_reached": sum(1 for row in rows if row["final_decision"] != "approve_trade"),
            "live_order_submitted": sum(1 for row in rows if row["live_order_submitted"]),
            "judge_skipped": sum(1 for row in rows if not row["expensive_judge_called"]),
            "planner_skipped": sum(1 for row in rows if not row["planner_called"]),
        },
        "lifecycle_summary": lifecycle_summary,
    }


def _write_reports(report: Dict[str, Any], *, json_out: Path, md_out: Path) -> None:
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Decision Pipeline v2 Audit",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Read-only: `{report['read_only']}`",
        f"- Tickers: `{report['summary']['ticker_count']}`",
        f"- Live orders submitted: `{report['summary']['live_order_submitted']}`",
        "",
        "| ticker | gate | planner | judge | final | risk | C43 | D2/D3 | why_wait | next_condition |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in report["tickers"]:
        lines.append(
            "| {ticker} | {gate} | {planner} | {judge} | {final} | {risk} | {c43} | {d2d3} | {why} | {next} |".format(
                ticker=row["ticker"],
                gate=row["entry_gate_decision"],
                planner="called" if row["planner_called"] else row["planner_skip_reason"],
                judge="called" if row["expensive_judge_called"] else row["judge_skip_reason"],
                final=row["final_decision"],
                risk=row["hard_risk_status"],
                c43=row["phase_c43_status"],
                d2d3=row["d2_d3_status"],
                why=str(row["why_wait"]).replace("|", "/")[:180],
                next=str(row["next_condition_to_watch"]).replace("|", "/")[:160],
            )
        )
    md_out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build read-only Decision Pipeline v2 audit reports.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--md-out", default=str(DEFAULT_MD_OUT))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_decision_pipeline_v2_audit(root=args.root)
    _write_reports(report, json_out=Path(args.json_out), md_out=Path(args.md_out))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"wrote {args.json_out} and {args.md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_decision_pipeline_v2_audit", "main", "parse_args"]
