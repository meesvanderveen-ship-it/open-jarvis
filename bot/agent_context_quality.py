from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List


CONTEXT_FIELDS = [
    "ticker", "timeframe", "current_price", "ohlcv", "multi_timeframe", "trend", "volume",
    "support_resistance", "atr", "spread", "orderbook_depth", "liquidity", "fees",
    "slippage_estimate", "max_quote", "min_order_rules", "product_precision",
    "open_positions", "open_orders", "pending_opportunities", "recent_invalidated_setups",
    "last_failed_submit_reason", "market_regime", "neural_learning_context",
    "stop_target_distance", "risk_reward", "reward_to_fee", "reward_to_risk",
    "invalidation_level", "trigger_level", "setup_type", "confidence", "do_not_chase",
]


def _load_jsonl(path: Path, limit: int = 200) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except Exception:
                continue
            if isinstance(data, dict):
                rows.append(data)
    return rows[-limit:]


def _has(mapping: Dict[str, Any], *keys: str) -> bool:
    cur: Any = mapping
    for key in keys:
        if not isinstance(cur, dict) or key not in cur or cur.get(key) in (None, "", [], {}):
            return False
        cur = cur.get(key)
    return True


def _row_context(row: Dict[str, Any]) -> Dict[str, bool]:
    fp = row.get("feature_pack") if isinstance(row.get("feature_pack"), dict) else {}
    judge = row.get("judge") if isinstance(row.get("judge"), dict) else {}
    plan = row.get("trade_plan") if isinstance(row.get("trade_plan"), dict) else {}
    dc = fp.get("decision_context") if isinstance(fp.get("decision_context"), dict) else {}
    market = fp.get("market") if isinstance(fp.get("market"), dict) else {}
    indicators = fp.get("indicators") if isinstance(fp.get("indicators"), dict) else {}
    structure = fp.get("structure") if isinstance(fp.get("structure"), dict) else {}
    return {
        "ticker": bool(row.get("ticker") or fp.get("ticker")),
        "timeframe": bool(indicators),
        "current_price": bool(market.get("mid_price") or fp.get("current_price")),
        "ohlcv": _has(fp, "raw_context"),
        "multi_timeframe": all(tf in indicators for tf in ("15m", "1h", "4h")),
        "trend": bool(indicators and structure),
        "volume": _has(fp, "microstructure"),
        "support_resistance": bool(structure.get("nearest_support") or structure.get("nearest_resistance")),
        "atr": any(isinstance(indicators.get(tf), dict) and indicators[tf].get("atr_14") for tf in indicators),
        "spread": bool(market.get("spread_pct") or _has(fp, "orderbook_context", "spread_pct")),
        "orderbook_depth": _has(fp, "orderbook_context"),
        "liquidity": bool(market.get("liquidity_score") or _has(fp, "orderbook_context")),
        "fees": _has(fp, "risk_context"),
        "slippage_estimate": bool(market.get("slippage_estimate") or _has(fp, "orderbook_summary", "slippage_estimate")),
        "max_quote": _has(fp, "decision_context", "live_order_size_policy"),
        "min_order_rules": bool(dc.get("product_rules") or fp.get("product_rules") or fp.get("exchange_rules")),
        "product_precision": bool(dc.get("product_rules") or fp.get("product_rules") or fp.get("exchange_rules")),
        "open_positions": _has(fp, "risk_context", "open_positions_count"),
        "open_orders": bool(dc.get("pending_order_intent") or _has(fp, "risk_context", "open_orders_count")),
        "pending_opportunities": bool(dc.get("pending_trade_plan") or row.get("pending_trade_plan")),
        "recent_invalidated_setups": bool(row.get("decision_outcomes") or dc.get("pending_trade_plan")),
        "last_failed_submit_reason": bool(dc.get("last_failed_submit_reason") or dc.get("recent_submit_rejections") or dc.get("recent_exchange_rejections")),
        "market_regime": bool(row.get("regime") or dc.get("external_context")),
        "neural_learning_context": bool(dc.get("neural_shadow_policy") or dc.get("live_learning") or row.get("recent_reflections")),
        "stop_target_distance": bool(plan.get("stop_loss") and (plan.get("take_profit_1") or plan.get("target_price_1"))),
        "risk_reward": bool(plan.get("risk_notes") or judge.get("objective_score") is not None),
        "reward_to_fee": "reward_to_fee" in json.dumps(row, default=str),
        "reward_to_risk": "reward_to_risk" in json.dumps(row, default=str),
        "invalidation_level": bool(plan.get("invalidation") or plan.get("stop_loss") or judge.get("invalidation_price")),
        "trigger_level": bool(plan.get("trigger") or plan.get("trigger_price") or judge.get("trigger")),
        "setup_type": bool(plan.get("setup_type") or judge.get("setup_type")),
        "confidence": bool(plan.get("confidence") or judge.get("confidence")),
        "do_not_chase": bool(plan.get("do_not_chase_above") or judge.get("do_not_chase_above")),
    }


def build_context_matrix(root: str | Path = ".", limit: int = 200) -> List[Dict[str, Any]]:
    project = Path(root)
    rows = _load_jsonl(project / "logs/analysis.jsonl", limit=limit)
    availability = [_row_context(row) for row in rows]
    out: List[Dict[str, Any]] = []
    for field in CONTEXT_FIELDS:
        present = sum(1 for row in availability if row.get(field))
        pct = (present / len(availability)) if availability else 0.0
        available = pct > 0
        to_analysis = available
        to_judge = to_analysis or field in {"setup_type", "confidence", "invalidation_level", "trigger_level", "do_not_chase"}
        priority = "P0" if field in {"product_precision", "min_order_rules", "last_failed_submit_reason"} and not to_judge else "P1" if pct < 0.5 else "P3"
        out.append({
            "context_field": field,
            "available_in_code": True,
            "available_in_logs": available,
            "available_to_analysis_agent": to_analysis,
            "available_to_final_judge": to_judge,
            "available_to_orderbook_planner": field in {"spread", "orderbook_depth", "liquidity", "reward_to_fee", "reward_to_risk", "invalidation_level", "trigger_level", "do_not_chase", "product_precision", "min_order_rules"},
            "available_to_submitter": field in {"product_precision", "min_order_rules", "max_quote", "open_orders"},
            "available_to_exit_manager": field in {"open_positions", "open_orders", "invalidation_level", "stop_target_distance", "product_precision", "min_order_rules"},
            "source_file": "logs/analysis.jsonl",
            "observed_ratio": round(pct, 4),
            "missing_reason": "" if available else "not observed in recent analysis rows",
            "recommended_fix": _recommendation(field),
            "priority": priority,
        })
    return out


def _recommendation(field: str) -> str:
    if field in {"product_precision", "min_order_rules"}:
        return "Inject product_rules into feature_pack decision_context before planner/judge and require submitter precision audit."
    if field == "last_failed_submit_reason":
        return "Summarize recent phase_c_live_submit rejects into decision_context for planner/judge and audit."
    if field in {"reward_to_fee", "reward_to_risk"}:
        return "Compute numeric ratios before final judge and deterministic orderbook preview."
    return "Keep current route; add schema presence test if this field becomes decision-critical."


def build_agent_context_quality_report(root: str | Path = ".", limit: int = 200) -> Dict[str, Any]:
    project = Path(root)
    rows = _load_jsonl(project / "logs/analysis.jsonl", limit=limit)
    submit_rows = _load_jsonl(project / "logs/phase_c_live_submit.jsonl", limit=200)
    setup_counts = Counter(str((row.get("judge") or {}).get("setup_type") or (row.get("trade_plan") or {}).get("setup_type") or "unknown") for row in rows)
    product_context_rows = 0
    reject_context_rows = 0
    execution_feasibility_rows = 0
    for row in rows:
        fp = row.get("feature_pack") if isinstance(row.get("feature_pack"), dict) else {}
        dc = fp.get("decision_context") if isinstance(fp.get("decision_context"), dict) else {}
        product_context_rows += int(bool(dc.get("product_rules") or fp.get("product_rules") or fp.get("exchange_rules")))
        reject_context_rows += int(bool(dc.get("recent_exchange_rejections")))
        execution_feasibility_rows += int(bool(dc.get("execution_feasibility") or fp.get("execution_feasibility")))
    wait_reasons = Counter()
    for row in rows:
        judge = row.get("judge") if isinstance(row.get("judge"), dict) else {}
        if str(judge.get("decision") or "").lower() == "wait":
            reason = str(judge.get("trigger_wait_reason") or (judge.get("reasons") or ["wait"])[0])
            wait_reasons[reason[:120]] += 1
    return {
        "phase": "agent_context_quality_audit_v1",
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "runtime_proof": {
            "decision_rows": len(rows),
            "tickers_overconsidered": len({row.get("ticker") for row in rows if row.get("ticker")}),
            "judge_called": sum(1 for row in rows if (row.get("judge") or {}).get("expensive_judge_called")),
            "valid_trade_plans": sum(1 for row in rows if (row.get("trade_plan") or {}).get("valid_trade_plan")),
            "opportunity_memory_candidates_estimated": sum(1 for row in rows if str((row.get("judge") or {}).get("decision") or "").lower() == "wait" and (row.get("trade_plan") or {}).get("plan_action") != "no_plan"),
            "submit_attempts_seen": sum(1 for row in submit_rows if row.get("live_submission_attempted")),
            "submit_reject_reasons": Counter(str(row.get("reject_reason") or row.get("status") or "unknown") for row in submit_rows if row.get("live_submission_attempted")),
            "precision_reject_reasons": Counter(str(row.get("reject_reason") or row.get("status") or "unknown") for row in submit_rows if str(row.get("reject_reason") or row.get("status") or "") in {"INVALID_PRICE_PRECISION", "INVALID_SIZE_PRECISION"}),
            "analysis_rows_with_product_rules": product_context_rows,
            "analysis_rows_with_recent_exchange_rejections": reject_context_rows,
            "analysis_rows_with_execution_feasibility": execution_feasibility_rows,
            "setup_type_counts": setup_counts,
            "dominant_wait_reasons": wait_reasons,
        },
        "matrix": build_context_matrix(project, limit=limit),
    }


__all__ = ["CONTEXT_FIELDS", "build_agent_context_quality_report", "build_context_matrix"]
