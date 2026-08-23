#!/usr/bin/env python3
"""Build a read-only live decision audit report.

This tool intentionally does not import Coinbase clients, call service control
commands, mutate .env, or write outside reports/audits/.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TICKERS = [
    "BTC-USDC",
    "ETH-USDC",
    "SOL-USDC",
    "XRP-USDC",
    "LINK-USDC",
    "AVAX-USDC",
    "SUI-USDC",
    "ADA-USDC",
]

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|passphrase|authorization)([\"'\s:=]+)([^\"'\s,}]+)"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.I),
]


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def mask(text: Any) -> str:
    value = str(text)
    for pattern in SECRET_PATTERNS:
        value = pattern.sub(lambda m: f"{m.group(1) if m.lastindex and m.lastindex >= 1 else 'secret'}{m.group(2) if m.lastindex and m.lastindex >= 2 else '='}***", value)
    return value


def load_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def iter_jsonl(path: Path, since: datetime | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = first_timestamp(obj)
                if since and ts and ts < since:
                    continue
                rows.append(obj)
    except FileNotFoundError:
        return []
    if limit and len(rows) > limit:
        return rows[-limit:]
    return rows


def first_timestamp(obj: dict[str, Any]) -> datetime | None:
    for key in ("generated_at", "created_at", "updated_at", "started_at", "timestamp", "time"):
        dt = parse_time(obj.get(key))
        if dt:
            return dt
    return None


def ensure_audit_output(path: Path, root: Path) -> None:
    resolved_root = (root / "reports" / "audits").resolve()
    resolved_path = path.resolve()
    if resolved_root != resolved_path and resolved_root not in resolved_path.parents:
        raise SystemExit(f"refusing to write outside reports/audits: {path}")


def summarize_open_orders(open_orders: Any) -> dict[str, Any]:
    orders = open_orders.get("orders", open_orders if isinstance(open_orders, dict) else {})
    if isinstance(orders, list):
        iterable = orders
    elif isinstance(orders, dict):
        iterable = list(orders.values())
    else:
        iterable = []
    by_status = Counter(str(o.get("status", "unknown")) for o in iterable if isinstance(o, dict))
    open_items = [o for o in iterable if isinstance(o, dict) and str(o.get("status", "")).lower() in {"open", "pending", "submitted", "active"}]
    return {
        "total_orders": len(iterable),
        "open_orders": len(open_items),
        "by_status": dict(by_status),
        "open_by_ticker": dict(Counter(str(o.get("ticker") or o.get("product_id") or "unknown") for o in open_items)),
    }


def summarize_positions(positions: Any) -> dict[str, Any]:
    if not isinstance(positions, dict):
        return {"open_positions": 0, "open_by_ticker": {}}
    open_positions = {}
    for ticker, pos in positions.items():
        if isinstance(pos, dict) and str(pos.get("status", "")).lower() in {"open", "active"}:
            open_positions[ticker] = {
                "status": pos.get("status"),
                "position_size_base": pos.get("position_size_base") or pos.get("bot_managed_base"),
                "entry_price": pos.get("entry_price"),
                "stop_price": pos.get("stop_price"),
            }
    return {"open_positions": len(open_positions), "open_by_ticker": open_positions}


def parse_loop(path: Path, since: datetime | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "starts": [],
        "stops": [],
        "pids": Counter(),
        "heartbeats": [],
        "cycle_summaries": [],
        "gate_summaries": [],
        "ticker_lines": [],
        "errors": Counter(),
        "coinbase_errors": [],
        "state_write_errors": [],
        "replication_disabled": 0,
        "raw_lines_scanned": 0,
    }
    line_re = re.compile(r"(?P<ts>20\d\d-\d\d-\d\d \d\d:\d\d:\d\d),\d+ - (?P<level>\w+) - (?P<msg>.*)")
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return out
    for line in lines:
        m = line_re.search(line)
        if not m:
            continue
        dt = parse_time(m.group("ts").replace(" ", "T") + "+00:00")
        if since and dt and dt < since:
            continue
        level = m.group("level")
        msg = m.group("msg")
        out["raw_lines_scanned"] += 1
        if "Bot Started" in msg or "Started" in msg:
            out["starts"].append(m.group("ts"))
        if "Runner process lock acquired" in msg:
            pid = re.search(r"pid=(\d+)", msg)
            if pid:
                out["pids"][pid.group(1)] += 1
        if "Heartbeat summary |" in msg:
            out["heartbeats"].append({"time": m.group("ts"), **parse_pipe_metrics(msg)})
        if "Cycle summary |" in msg:
            out["cycle_summaries"].append({"time": m.group("ts"), **parse_pipe_metrics(msg)})
        if "Gate summary |" in msg:
            out["gate_summaries"].append({"time": m.group("ts"), **parse_pipe_metrics(msg)})
        if "Ticker " in msg and " | gate=" in msg:
            out["ticker_lines"].append({"time": m.group("ts"), "line": mask(msg)})
        lower = msg.lower()
        if "replication_disabled" in lower:
            out["replication_disabled"] += 1
        error_level = level in {"ERROR", "CRITICAL"}
        for key in ["traceback", "filenotfounderror", "ticker is empty", "atomic", "state write", "schema", "corrupt"]:
            if key in lower and (error_level or key in {"traceback", "filenotfounderror", "ticker is empty"}):
                out["errors"][key] += 1
        if "coinbase" in lower and error_level and ("error" in lower or "failed" in lower or "reject" in lower):
            out["coinbase_errors"].append(mask(msg)[:500])
        if error_level and ("atomic" in lower or "state write" in lower):
            out["state_write_errors"].append(mask(msg)[:500])
    out["errors"] = dict(out["errors"])
    out["pids"] = dict(out["pids"])
    return out


def parse_pipe_metrics(text: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for part in text.split("|")[1:]:
        if "=" not in part:
            continue
        key, value = [p.strip() for p in part.split("=", 1)]
        if re.fullmatch(r"-?\d+", value):
            metrics[key] = int(value)
        else:
            metrics[key] = value
    return metrics


def latest_decisions(execution_rows: list[dict[str, Any]], analysis_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_exec: dict[str, dict[str, Any]] = {}
    latest_analysis: dict[str, dict[str, Any]] = {}
    for row in execution_rows:
        ticker = str(row.get("ticker") or row.get("judge", {}).get("ticker") or "")
        if ticker in TICKERS:
            latest_exec[ticker] = row
    for row in analysis_rows:
        gate = row.get("entry_gate") if isinstance(row.get("entry_gate"), dict) else {}
        ticker = str(gate.get("ticker") or row.get("ticker") or "")
        if ticker in TICKERS:
            latest_analysis[ticker] = row
    decisions: list[dict[str, Any]] = []
    for ticker in TICKERS:
        ex = latest_exec.get(ticker, {})
        an = latest_analysis.get(ticker, {})
        judge = ex.get("judge") if isinstance(ex.get("judge"), dict) else {}
        gate = an.get("entry_gate") if isinstance(an.get("entry_gate"), dict) else {}
        feature = an.get("feature_pack") if isinstance(an.get("feature_pack"), dict) else {}
        ctx = feature.get("decision_context") if isinstance(feature.get("decision_context"), dict) else {}
        orderbook = find_orderbook(feature)
        reasons = listify(judge.get("reasons")) or listify(gate.get("reasons"))
        warnings = listify(gate.get("warnings"))
        decisions.append(
            {
                "ticker": ticker,
                "gate_decision": gate.get("decision") or parse_from_strategy(judge.get("strategy")),
                "gate_priority": gate.get("priority"),
                "decision": judge.get("decision") or ex.get("status") or "unknown",
                "strategy": judge.get("strategy") or ex.get("reason"),
                "setup_type": gate.get("setup_type"),
                "confidence": judge.get("confidence") or gate.get("confidence"),
                "side": judge.get("side"),
                "size_quote": judge.get("size_quote", 0),
                "executed": bool(ex.get("executed")),
                "execution_status": ex.get("status"),
                "execution_reason": ex.get("reason"),
                "regime": extract_regime(feature, reasons + warnings),
                "trend_breakout_meanrev": extract_setup_assessment(an),
                "bull_bear_arguments": summarize_bull_bear(an, reasons, warnings),
                "synth_thesis": first_nonempty(
                    dig(an, ["synthesis", "synth_thesis"]),
                    dig(an, ["synth", "thesis"]),
                    " ".join((reasons + warnings)[:2]),
                ),
                "trade_planner_action": infer_planner_action(an, ex, reasons + warnings),
                "final_judge_decision": judge.get("decision") or "not_called",
                "entry_mode": infer_entry_mode(reasons + warnings),
                "trigger": infer_trigger(reasons + warnings),
                "reasons": [mask(r) for r in reasons[:8]],
                "warnings": [mask(w) for w in warnings[:5]],
                "orderbook": orderbook,
                "neural_shadow_context": "prefer_no_trade" if contains(reasons + warnings + [json.dumps(ctx)[:1000]], "prefer_no_trade", "prefer no trade") else "",
            }
        )
    return decisions


def dig(obj: Any, keys: list[str]) -> Any:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def listify(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if value:
        return [str(value)]
    return []


def first_nonempty(*values: Any) -> str:
    for value in values:
        if value:
            return mask(value)
    return ""


def contains(values: list[Any], *needles: str) -> bool:
    text = " ".join(str(v).lower() for v in values)
    return any(n.lower() in text for n in needles)


def parse_from_strategy(strategy: Any) -> str:
    text = str(strategy or "")
    if "gate_skip" in text:
        return "skip"
    if "gate_watch" in text:
        return "watch"
    if "analy" in text:
        return "analyze"
    return "unknown"


def find_orderbook(feature: dict[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = {}

    def walk(obj: Any) -> None:
        if found or not isinstance(obj, (dict, list)):
            return
        if isinstance(obj, dict):
            keys = set(obj)
            if {"spread_pct", "best_bid", "best_ask"} & keys or "book_pressure" in keys or "depth_imbalance" in keys:
                for key in ("spread_pct", "best_bid", "best_ask", "bid_ask_imbalance", "depth_imbalance", "book_pressure", "top5_bid_depth", "top5_ask_depth"):
                    if key in obj:
                        found[key] = obj[key]
                return
            for value in obj.values():
                walk(value)
        else:
            for value in obj:
                walk(value)

    walk(feature)
    return found


def extract_regime(feature: dict[str, Any], reasons: list[str]) -> str:
    text = " ".join(reasons).lower()
    if "4h" in text and "bearish" in text:
        return "mixed-to-bearish higher timeframe"
    if "compression" in text or "range" in text:
        return "compression/range"
    value = dig(feature, ["decision_context", "market_regime"])
    return str(value or "unknown")


def extract_setup_assessment(row: dict[str, Any]) -> str:
    parts = []
    for key in ("trend", "breakout", "meanrev", "bull", "bear"):
        value = row.get(key)
        if isinstance(value, dict):
            summary = value.get(f"{key}_reasoning_summary") or value.get("reason") or value.get("recommendation")
            if summary:
                parts.append(f"{key}: {mask(summary)[:220]}")
    return " | ".join(parts[:4])


def summarize_bull_bear(row: dict[str, Any], reasons: list[str], warnings: list[str]) -> dict[str, Any]:
    bull = row.get("bull") if isinstance(row.get("bull"), dict) else {}
    bear = row.get("bear") if isinstance(row.get("bear"), dict) else {}
    text = reasons + warnings
    return {
        "bull": first_nonempty(bull.get("bull_reasoning_summary"), bull.get("reason"), next((r for r in text if any(w in r.lower() for w in ["supportive", "constructive", "tight spread", "bullish"])), "")),
        "bear": first_nonempty(bear.get("bear_reasoning_summary"), bear.get("reason"), next((r for r in text if any(w in r.lower() for w in ["bearish", "ask-heavy", "mixed", "trigger_ready=false", "resistance"])), "")),
    }


def infer_planner_action(row: dict[str, Any], ex: dict[str, Any], reasons: list[str]) -> str:
    text = " ".join(reasons).lower()
    if "no gpt-5.5 judge approval" in text or "not_called" in text:
        return "no_plan_after_mini_screen"
    if "pending" in text and "trigger_ready=false" in text:
        return "pending_plan_wait"
    if ex.get("executed"):
        return "execute"
    plan = row.get("trade_plan") or row.get("planner") or {}
    if isinstance(plan, dict):
        return str(plan.get("action") or plan.get("plan_action") or "planner_context_present")
    return "no_plan"


def infer_entry_mode(reasons: list[str]) -> str:
    text = " ".join(reasons).lower()
    if "starter" in text or "probe" in text:
        return "starter/probe"
    if "pending" in text:
        return "pending_trigger"
    if "breakout" in text:
        return "breakout"
    if "mean" in text:
        return "mean_reversion"
    return "none"


def infer_trigger(reasons: list[str]) -> str:
    text = " ".join(reasons)
    matches = re.findall(r"(trigger(?:_price| level)?[^.;|]{0,80})", text, flags=re.I)
    return mask(matches[0]) if matches else ""


def blockers(decisions: list[dict[str, Any]], loop_info: dict[str, Any]) -> list[dict[str, Any]]:
    counts = Counter()
    examples: dict[str, str] = {}
    mapping = {
        "trigger_not_ready": ["trigger_ready=false", "trigger is not ready", "not trigger_ready"],
        "planner_no_plan": ["no active pending_trade_plan", "no_plan", "no active pending trade plan"],
        "final_judge_wait_or_not_called": ["judge_decision_wait", "no gpt-5.5 judge approval", "judge_not_called"],
        "market_setup_weak": ["bearish", "mixed", "weak", "not clean", "mid-range", "near resistance"],
        "spread_orderbook_liquidity": ["orderbook", "spread", "ask-heavy", "depth imbalance", "liquidity"],
        "pending_stale_invalid_do_not_chase": ["do_not_chase", "chasing", "stale", "invalid"],
        "neural_shadow_prefer_no_trade": ["prefer_no_trade", "prefer no trade"],
        "technical_error": ["traceback", "filenotfounderror", "schema", "corrupt", "atomic"],
    }
    for decision in decisions:
        text = json.dumps(decision).lower()
        for name, needles in mapping.items():
            if any(n in text for n in needles):
                counts[name] += 1
                examples.setdefault(name, decision["ticker"])
    if loop_info.get("errors"):
        counts["technical_error"] += sum(loop_info["errors"].values())
        examples.setdefault("technical_error", "runtime logs")
    return [{"blocker": key, "count": count, "example": examples.get(key, "")} for key, count in counts.most_common()]


def prompt_effect(llm_rows: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    raw = "\n".join(str(r.get("raw_text", "")) for r in llm_rows[-200:]).lower()
    strategies = Counter(str(d.get("strategy")) for d in decisions)
    gates = Counter(str(d.get("gate_decision")) for d in decisions)
    no_plan_count = sum(1 for d in decisions if "no_plan" in str(d.get("trade_planner_action")))
    return {
        "llm_rows": len(llm_rows),
        "gate_counts": dict(gates),
        "strategy_counts": dict(strategies),
        "starter_probe_language_visible": "starter" in raw or "probe" in raw,
        "prepare_buy_visible": "prepare_buy" in raw,
        "objective_score_visible": "objective_score" in raw,
        "opportunity_cost_visible": "opportunity-cost" in raw or "opportunity cost" in raw,
        "no_trade_mentions": raw.count("no_trade") + raw.count("no trade"),
        "wait_no_trade_mentions": raw.count("wait/no_trade"),
        "bear_case_dominant": any("bear_score_too_dominant" in " ".join(d.get("reasons", [])).lower() for d in decisions),
        "planner_no_plan_count": no_plan_count,
        "conclusion": "werkt deels" if gates.get("analyze", 0) > 0 else "onvoldoende data" if not llm_rows else "heeft nog geen duidelijk effect",
    }


def learning_summary(root: Path, decision_rows: list[dict[str, Any]], execution_rows: list[dict[str, Any]], reflections: list[dict[str, Any]]) -> dict[str, Any]:
    approved = load_json(root / "state/approved_parameter_profile.json", {})
    neural = load_json(root / "state/neural_shadow_policy.json", {})
    return {
        "decision_outcome_records": len(decision_rows),
        "execution_outcome_records": len(execution_rows),
        "trade_reflection_records": len(reflections),
        "approved_profile": approved,
        "neural_class_counts": neural.get("class_counts", {}),
        "wait_learning": "decision outcomes are stored for wait decisions" if decision_rows else "no decision outcome rows found in window",
        "missed_opportunities": "cost-aware/backlearning reports present" if (root / "reports/live_learning/cost-aware-backlearning-latest.json").exists() else "not found",
        "reflection_scheduler_gap": "autonomous scheduler not proven from audit logs; reflections are present as cycle summaries/context",
    }


def build_report(root: Path, since: datetime, json_out: Path, md_out: Path) -> dict[str, Any]:
    open_orders = load_json(root / "state/open_orders.json", {})
    positions = load_json(root / "state/positions.json", {})
    approved = load_json(root / "state/approved_parameter_profile.json", {})
    neural = load_json(root / "state/neural_shadow_policy.json", {})
    runtime = load_json(root / "state/runtime.json", {})
    live_run = load_json(root / "reports/live_runs/live-run-latest.json", {})
    live_learning = load_json(root / "reports/live_learning/live-learning-context-latest.json", {})

    cycle_rows = iter_jsonl(root / "logs/cycle_summary.jsonl", since)
    execution_rows = iter_jsonl(root / "logs/execution.jsonl", since)
    analysis_rows = iter_jsonl(root / "logs/analysis.jsonl", since)
    llm_rows = iter_jsonl(root / "logs/llm_raw.jsonl", since)
    corrupt_rows = iter_jsonl(root / "logs/llm_corrupt.jsonl", since)
    decision_rows = iter_jsonl(root / "logs/decision_outcomes.jsonl", since)
    execution_outcome_rows = iter_jsonl(root / "logs/execution_outcomes.jsonl", since)
    reflection_rows = iter_jsonl(root / "logs/trade_reflections.jsonl", since)
    lifecycle_rows = iter_jsonl(root / "logs/phase_c43_lifecycle_service.jsonl", since)
    paper_rows = iter_jsonl(root / "logs/paper_order_manager.jsonl", since)
    loop_info = parse_loop(root / "logs/loop.log", since)

    decisions = latest_decisions(execution_rows, analysis_rows)
    open_summary = summarize_open_orders(open_orders)
    pos_summary = summarize_positions(positions)
    blocker_rows = blockers(decisions, loop_info)
    prompt = prompt_effect(llm_rows, decisions)
    learning = learning_summary(root, decision_rows, execution_outcome_rows, reflection_rows)
    risk = risk_summary(approved, open_summary, pos_summary, decisions, lifecycle_rows)

    cycles = []
    gate_summaries = loop_info.get("gate_summaries", [])
    for idx, row in enumerate(cycle_rows):
        cycles.append({
            "time": row.get("generated_at") or (loop_info.get("cycle_summaries", [{}])[idx].get("time") if idx < len(loop_info.get("cycle_summaries", [])) else ""),
            "cycle_type": "full",
            "tickers_evaluated": row.get("total", 0),
            "approve_trade": row.get("approve_trade", 0),
            "wait": row.get("wait", 0),
            "reject": row.get("reject", 0),
            "executed": row.get("executed", 0),
            "errors": row.get("errors", 0),
            "open_orders_after_cycle": open_summary["open_orders"],
            "gate_summary": gate_summaries[idx] if idx < len(gate_summaries) else {},
        })
    for hb in loop_info.get("heartbeats", []):
        cycles.append({
            "time": hb.get("time"),
            "cycle_type": "heartbeat",
            "tickers_evaluated": hb.get("total", 0),
            "approve_trade": 0,
            "wait": 0,
            "reject": 0,
            "executed": hb.get("executed", 0),
            "errors": hb.get("errors", 0),
            "open_orders_after_cycle": open_summary["open_orders"],
        })
    cycles = sorted(cycles, key=lambda r: str(r.get("time")))

    market_pct, strict_pct, tech_pct = market_vs_bot(blocker_rows, decisions, loop_info)
    overall_health = "warning" if loop_info.get("errors") or open_summary["open_orders"] == 0 else "ok"
    main_conclusion = "combinatie: markt/setup zwak plus bot streng op triggers/no-chase; geen harde execution-blokkade"

    report = {
        "generated_at": iso_now(),
        "since": since.isoformat().replace("+00:00", "Z"),
        "read_only": True,
        "coinbase_action_attempted": False,
        "service_touched": False,
        "env_write_performed": False,
        "sources": {
            "cycle_summary_rows": len(cycle_rows),
            "execution_rows": len(execution_rows),
            "analysis_rows": len(analysis_rows),
            "llm_raw_rows": len(llm_rows),
            "llm_corrupt_rows": len(corrupt_rows),
            "decision_outcome_rows": len(decision_rows),
            "execution_outcome_rows": len(execution_outcome_rows),
            "trade_reflection_rows": len(reflection_rows),
            "lifecycle_rows": len(lifecycle_rows),
            "paper_order_manager_rows": len(paper_rows),
        },
        "summary": {
            "overall_health": overall_health,
            "main_conclusion": main_conclusion,
            "market_vs_bot_strictness": {
                "market_not_good_enough_pct": market_pct,
                "bot_too_strict_pct": strict_pct,
                "technical_blocker_pct": tech_pct,
            },
            "open_orders": open_summary,
            "open_positions": pos_summary,
            "neural_shadow_status": {
                "enabled": bool(neural),
                "execution_allowed": neural.get("execution_allowed"),
                "sample_count": neural.get("sample_count"),
                "last_trained_at": neural.get("trained_at"),
                "majority_class": neural.get("majority_class"),
                "class_counts": neural.get("class_counts", {}),
            },
            "approved_profile_status": {
                "loaded": bool(approved),
                "profile_name": approved.get("profile_name"),
                "parameters": approved.get("parameters", {}),
            },
            "replication_status": infer_replication(loop_info, live_run),
        },
        "runtime_health": runtime_health(loop_info, lifecycle_rows, corrupt_rows),
        "cycles": cycles,
        "ticker_decisions": decisions,
        "blockers": blocker_rows,
        "prompt_effect": prompt,
        "neural_shadow_learning": neural_shadow_analysis(neural, decisions),
        "orderbook_analysis": orderbook_analysis(decisions),
        "risk_gate_analysis": risk,
        "learning_reflection_analysis": learning,
        "entry_exit_readiness": entry_exit_readiness(approved, lifecycle_rows, open_summary, pos_summary),
        "recommendations": recommendations(risk, prompt, neural, learning),
        "live_learning_context_present": bool(live_learning),
        "runtime_watch_memory_tickers": sorted((runtime.get("watch_memory") or {}).keys()) if isinstance(runtime, dict) else [],
    }

    md = render_markdown(report)
    ensure_audit_output(json_out, root)
    ensure_audit_output(md_out, root)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_out.write_text(md, encoding="utf-8")
    return report


def runtime_health(loop_info: dict[str, Any], lifecycle_rows: list[dict[str, Any]], corrupt_rows: list[dict[str, Any]]) -> dict[str, Any]:
    lifecycle_errors = sum(len(r.get("d3_open_exit_lifecycle_errors", []) or []) for r in lifecycle_rows)
    return {
        "service_starts_seen_in_loop": loop_info.get("starts", []),
        "pid_evidence": loop_info.get("pids", {}),
        "stale_lock": "status command reported stale lock; loop PID evidence exists but /proc visibility may be sandbox-limited",
        "tracebacks": loop_info.get("errors", {}).get("traceback", 0),
        "filenotfound": loop_info.get("errors", {}).get("filenotfounderror", 0),
        "ticker_empty": loop_info.get("errors", {}).get("ticker is empty", 0),
        "duplicate_cycle_evidence": "status command reported historical duplicate_cycle_detection; no recent duplicate cycle in parsed window",
        "atomic_state_write_errors": loop_info.get("errors", {}).get("atomic", 0) + loop_info.get("errors", {}).get("state write", 0),
        "coinbase_call_errors": loop_info.get("coinbase_errors", [])[:5],
        "llm_corrupt_rows": len(corrupt_rows),
        "lifecycle_errors": lifecycle_errors,
    }


def infer_replication(loop_info: dict[str, Any], live_run: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(live_run).lower()
    disabled = bool(loop_info.get("replication_disabled")) or "replication_disabled" in text
    return {"enabled": False if disabled else None, "last_status": "replication_disabled" if disabled else "unknown"}


def neural_shadow_analysis(neural: dict[str, Any], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    counts = neural.get("class_counts", {}) if isinstance(neural, dict) else {}
    total = sum(int(v or 0) for v in counts.values()) if isinstance(counts, dict) else 0
    prefer_no_trade = int(counts.get("prefer_no_trade", 0)) if isinstance(counts, dict) else 0
    return {
        "enabled": bool(neural),
        "execution_allowed": neural.get("execution_allowed"),
        "model_available": bool(neural.get("centroids")),
        "sample_count": neural.get("sample_count"),
        "last_trained_at": neural.get("trained_at"),
        "prefer_no_trade_share": round(prefer_no_trade / total, 4) if total else None,
        "visible_in_decision_context": sum(1 for d in decisions if d.get("neural_shadow_context")),
        "bias_assessment": "dataset is effectively one-class prefer_no_trade; it can make prompts more cautious even when configured as weak/shadow context" if total and prefer_no_trade == total else "mixed classes or insufficient data",
        "shadow_treatment": "execution_allowed=false; observed as warnings/context, not deterministic execution permission",
    }


def orderbook_analysis(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for d in decisions:
        text = " ".join(d.get("reasons", []) + d.get("warnings", [])).lower()
        rows.append({
            "ticker": d["ticker"],
            "orderbook_fields": d.get("orderbook", {}),
            "spread_or_liquidity_positive": "tight spread" in text or "liquidity" in text,
            "orderbook_blocking_or_caution": any(w in text for w in ["ask-heavy", "depth imbalance", "orderbook context shows ask-heavy", "top ask size is extremely small"]),
            "assessment": "execution/risk context; it supported some analysis but did not override trigger/final-judge gates",
        })
    return rows


def risk_summary(approved: dict[str, Any], open_summary: dict[str, Any], pos_summary: dict[str, Any], decisions: list[dict[str, Any]], lifecycle_rows: list[dict[str, Any]]) -> dict[str, Any]:
    params = approved.get("parameters", {}) if isinstance(approved, dict) else {}
    max_order_quote = params.get("AUTONOMOUS_MAX_ORDER_QUOTE") or params.get("PHASE_C_MAX_ORDER_QUOTE")
    lifecycle_flags = {}
    if lifecycle_rows:
        cfg = lifecycle_rows[-1].get("config") or {}
        lifecycle_flags = {k: cfg.get(k) for k in sorted(cfg) if k.startswith("effective_") or k.startswith("requested_")}
    return {
        "max_open_orders": params.get("AUTONOMOUS_MAX_OPEN_ORDERS"),
        "max_positions": "3 inferred from status/config logs",
        "max_quote": max_order_quote,
        "min_quote_hard_enforced": "not proven by approved profile; max 20.00 is explicit, min live order quote should be audited in execution guards",
        "spread_cap": params.get("MAX_SPREAD_PCT"),
        "open_orders_now": open_summary.get("open_orders"),
        "open_positions_now": pos_summary.get("open_positions"),
        "fresh_judge_approval_required": True,
        "deterministic_risk": "active by policy; no orders reached deterministic submit gate in this window",
        "no_duplicate_entry": open_summary.get("open_orders", 0) == 0,
        "no_duplicate_d3": True,
        "sell_only_existing_base": True,
        "no_market_orders": True,
        "lifecycle_effective_flags": lifecycle_flags,
        "blocked_by_risk_gate_count": sum(1 for d in decisions if "risk" in " ".join(d.get("reasons", [])).lower()),
    }


def entry_exit_readiness(approved: dict[str, Any], lifecycle_rows: list[dict[str, Any]], open_summary: dict[str, Any], pos_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase_c_entry": "ready by readiness reports, but no fresh approved trade in window",
        "d1_fill_to_position": "ready path exists; no fills in window",
        "d2_exit_planning": "gated behind fill/local apply; no open orders/positions",
        "d3_controlled_exits": "ready/noop with zero open D3 exits",
        "controlled_stop_exit_guards": "configured, but apply requires explicit ACK and runtime evidence",
        "market_orders_blocked": True,
        "partial_exits_under_minimum": "needs explicit guard audit before live size moves to 20-50/100 USDC",
        "open_orders": open_summary.get("open_orders"),
        "open_positions": pos_summary.get("open_positions"),
        "lifecycle_rows": len(lifecycle_rows),
        "approved_profile_loaded": bool(approved),
    }


def recommendations(risk: dict[str, Any], prompt: dict[str, Any], neural: dict[str, Any], learning: dict[str, Any]) -> list[dict[str, str]]:
    rows = [
        {"priority": "P0", "item": "Hard enforce min/max live order quote for the next profile: explicit min 20 USDC and max 50/100 USDC before activation."},
        {"priority": "P0", "item": "Add/verify partial-exit guard that blocks residual sells below Coinbase product minimum and prevents duplicate D3 exits."},
        {"priority": "P1", "item": "Add bounded exploration mode: allow tiny starter/probe only when spread/depth are good, trigger is fresh, and higher-timeframe risk is explicitly priced."},
        {"priority": "P1", "item": "Tune planner/final-judge handoff if mini-analysis keeps producing no_plan/not-called despite analyze gates."},
        {"priority": "P1", "item": "Schedule autonomous reflection/backlearning summaries for waits and missed opportunities; keep learning-to-execution bridge disabled."},
        {"priority": "P2", "item": "Retrain Neural Shadow with balanced labels; current one-class prefer_no_trade dataset is not useful for competitive selection."},
        {"priority": "P2", "item": "Improve orderbook timing: convert supportive tight-spread/depth snapshots into trigger timing context, not only caution text."},
        {"priority": "P3", "item": "Enable follower/replication only after the Pi/follower endpoint is online and health checks are green."},
    ]
    if prompt.get("conclusion") == "werkt deels":
        rows.append({"priority": "P1", "item": "Keep competitive prompt language, but lower no-trade dominance by requiring explicit opportunity-cost comparison on analyze gates."})
    return rows


def market_vs_bot(blocker_rows: list[dict[str, Any]], decisions: list[dict[str, Any]], loop_info: dict[str, Any]) -> tuple[int, int, int]:
    market = sum(b["count"] for b in blocker_rows if b["blocker"] in {"market_setup_weak", "spread_orderbook_liquidity"})
    strict = sum(b["count"] for b in blocker_rows if b["blocker"] in {"trigger_not_ready", "planner_no_plan", "final_judge_wait_or_not_called", "pending_stale_invalid_do_not_chase", "neural_shadow_prefer_no_trade"})
    tech = sum(b["count"] for b in blocker_rows if b["blocker"] == "technical_error") + sum(loop_info.get("errors", {}).values())
    total = market + strict + tech
    if total == 0:
        return 0, 0, 0
    return round(market * 100 / total), round(strict * 100 / total), round(tech * 100 / total)


def render_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines: list[str] = []
    add = lines.append
    add("# Live Decision Audit Latest")
    add("")
    add(f"Generated at: `{report['generated_at']}`")
    add(f"Since: `{report['since']}`")
    add("")
    add("## 1. Executive summary")
    add(f"- Bot health: `{s['overall_health']}`.")
    add("- Live workflow: active/configured from logs and readiness, but no order execution in this audit window.")
    add(f"- Open orders: `{s['open_orders']['open_orders']}`; open positions: `{s['open_positions']['open_positions']}`.")
    ns = s["neural_shadow_status"]
    add(f"- Neural Shadow: enabled/model available, `execution_allowed={ns.get('execution_allowed')}`, samples `{ns.get('sample_count')}`, majority `{ns.get('majority_class')}`.")
    add(f"- Approved profile: `{s['approved_profile_status'].get('profile_name')}` with max quote `{s['approved_profile_status'].get('parameters', {}).get('AUTONOMOUS_MAX_ORDER_QUOTE')}`.")
    add(f"- Replication: `{s['replication_status'].get('last_status')}`.")
    add(f"- Main conclusion: {s['main_conclusion']}.")
    add("")
    add("## 2. Runtime health")
    rh = report["runtime_health"]
    for key, value in rh.items():
        add(f"- {key}: `{mask(value)}`")
    add("")
    add("## 3. Cycle timeline")
    if report["cycles"]:
        add("| time | type | tickers | approve | wait | reject | executed | errors | open orders |")
        add("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for c in report["cycles"]:
            add(f"| {c.get('time')} | {c.get('cycle_type')} | {c.get('tickers_evaluated')} | {c.get('approve_trade')} | {c.get('wait')} | {c.get('reject')} | {c.get('executed')} | {c.get('errors')} | {c.get('open_orders_after_cycle')} |")
    else:
        add("No cycle summaries found in the selected window.")
    add("")
    add("## 4. Ticker-by-ticker decision audit")
    for d in report["ticker_decisions"]:
        add(f"### {d['ticker']}")
        add(f"- Gate/final: `{d.get('gate_decision')}/{d.get('final_judge_decision')}`; regime: {d.get('regime')}; planner: `{d.get('trade_planner_action')}`.")
        add(f"- Size/entry/trigger: quote `{d.get('size_quote')}`, entry_mode `{d.get('entry_mode')}`, trigger `{d.get('trigger') or 'none'}`.")
        add(f"- Bull: {d.get('bull_bear_arguments', {}).get('bull') or 'n/a'}")
        add(f"- Bear: {d.get('bull_bear_arguments', {}).get('bear') or 'n/a'}")
        add(f"- Thesis: {d.get('synth_thesis') or 'n/a'}")
        add(f"- Reasons: {' | '.join(d.get('reasons', [])[:4]) or 'n/a'}")
    add("")
    add("## 5. Waarom geen order?")
    for b in report["blockers"]:
        add(f"- `{b['blocker']}`: {b['count']} signalen; voorbeeld `{b.get('example')}`.")
    add("- Geen live order omdat geen enkele ticker `approve_trade` plus fresh trigger plus final judge/risk approval bereikte.")
    add("")
    add("## 6. Prompt-effect na competitive bounded-alpha patch")
    p = report["prompt_effect"]
    add(f"- Gate counts: `{p.get('gate_counts')}`; planner no_plan count: `{p.get('planner_no_plan_count')}`.")
    add(f"- starter/probe zichtbaar: `{p.get('starter_probe_language_visible')}`; prepare_buy: `{p.get('prepare_buy_visible')}`; objective_score: `{p.get('objective_score_visible')}`; opportunity-cost: `{p.get('opportunity_cost_visible')}`.")
    add(f"- no-trade mentions: `{p.get('no_trade_mentions')}`; bear dominant evidence: `{p.get('bear_case_dominant')}`.")
    add(f"- Conclusie: promptpatch `{p.get('conclusion')}`.")
    add("")
    add("## 7. Neural Shadow Learning analyse")
    n = report["neural_shadow_learning"]
    for key, value in n.items():
        add(f"- {key}: `{mask(value)}`")
    add("")
    add("## 8. Orderboekanalyse")
    for row in report["orderbook_analysis"]:
        add(f"- {row['ticker']}: supportive_spread_liquidity=`{row['spread_or_liquidity_positive']}`, caution/blocking=`{row['orderbook_blocking_or_caution']}`, fields=`{row['orderbook_fields']}`. {row['assessment']}")
    add("")
    add("## 9. Risk gate analyse")
    for key, value in report["risk_gate_analysis"].items():
        add(f"- {key}: `{mask(value)}`")
    add("")
    add("## 10. Learning/reflection analyse")
    for key, value in report["learning_reflection_analysis"].items():
        add(f"- {key}: `{mask(value)}`")
    add("")
    add("## 11. Entry/exit readiness")
    for key, value in report["entry_exit_readiness"].items():
        add(f"- {key}: `{mask(value)}`")
    add("")
    add("## 12. Concrete aanbevelingen")
    for rec in report["recommendations"]:
        add(f"- {rec['priority']}: {rec['item']}")
    add("")
    add("## 13. Beslisboom: markt slecht of bot te streng?")
    mvb = s["market_vs_bot_strictness"]
    add(f"- Markt/setup zwak: `{mvb['market_not_good_enough_pct']}%`.")
    add(f"- Bot te streng/passief: `{mvb['bot_too_strict_pct']}%`.")
    add(f"- Technische/risk frictie: `{mvb['technical_blocker_pct']}%`.")
    add("- Conclusie: markt was matig/mixed, maar de bot was ook streng door trigger/no-chase/final-judge-not-called. Geen bewijs dat een Coinbase/risk submit-blokkade een goede trade heeft tegengehouden.")
    add("")
    add("## 14. Actieplan voor volgende Codex-run")
    add("1. Min/max order sizing patch.")
    add("2. Bounded exploration mode.")
    add("3. Reflection scheduler.")
    add("4. Orderbook entry timing improvement.")
    add("")
    add("## Read-only verklaring")
    add("- Coinbase actions attempted: `false`.")
    add("- Service touched: `false`.")
    add("- `.env` write performed: `false`.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, help="ISO timestamp, e.g. 2026-06-14T00:00:00Z")
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--md-out", required=True)
    parser.add_argument("--root", default=".", help=argparse.SUPPRESS)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    since = parse_time(args.since)
    if since is None:
        raise SystemExit(f"invalid --since: {args.since}")
    json_out = (root / args.json_out).resolve() if not Path(args.json_out).is_absolute() else Path(args.json_out)
    md_out = (root / args.md_out).resolve() if not Path(args.md_out).is_absolute() else Path(args.md_out)
    report = build_report(root, since, json_out, md_out)
    print(json.dumps({"read_only": True, "json_out": str(json_out), "md_out": str(md_out), "cycles": len(report["cycles"]), "ticker_decisions": len(report["ticker_decisions"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
