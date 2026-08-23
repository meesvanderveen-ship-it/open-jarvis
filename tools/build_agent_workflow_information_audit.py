#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.agent_context_quality import build_context_matrix
from bot.atomic_io import atomic_write_json, atomic_write_text
from bot.setup_pattern_library import build_setup_pattern_status

DEFAULT_JSON = Path("reports/audits/agent-workflow-information-audit-latest.json")
DEFAULT_MD = Path("reports/audits/agent-workflow-information-audit-latest.md")
BACKLOG_JSON = Path("reports/audits/agent-workflow-hardening-backlog-latest.json")
BACKLOG_MD = Path("reports/audits/agent-workflow-hardening-backlog-latest.md")
OSS_JSON = Path("reports/research/open-source-agent-pattern-comparison-latest.json")
OSS_MD = Path("reports/research/open-source-agent-pattern-comparison-latest.md")


def _component(
    name: str,
    role: str,
    entrypoint: str,
    called_by: str,
    calls: list[str],
    authority: str,
    gaps: list[str],
    status: str,
    *,
    input_context: Optional[dict[str, bool]] = None,
    logs: Optional[list[str]] = None,
    state: Optional[list[str]] = None,
    can_block: bool = True,
) -> dict[str, Any]:
    default_context = {
        "ticker": True,
        "ohlcv": True,
        "multi_timeframe": True,
        "orderbook": True,
        "spread_depth": True,
        "fees": True,
        "positions": True,
        "open_orders": True,
        "pending_opportunities": False,
        "recent_failed_attempts": False,
        "market_regime": True,
        "macro_context": True,
        "learning_context": True,
        "precision_rules": False,
        "min_order_rules": False,
        "risk_budget": True,
    }
    if input_context:
        default_context.update(input_context)
    return {
        "agent_or_component": name,
        "role": role,
        "entrypoint": entrypoint,
        "called_by": called_by,
        "calls": calls,
        "input_context_available": default_context,
        "output_schema": "strict JSON/typed dict" if "LLM" in role or "judge" in name.lower() else "dict/report",
        "decision_authority": authority,
        "can_authorize_live_order": authority == "execute_live",
        "can_block_live_order": can_block,
        "logs_written": logs or [],
        "state_written": state or [],
        "test_coverage": "targeted pytest exists or POC test added",
        "gaps": gaps,
        "status": status,
    }


def build_agent_map() -> list[dict[str, Any]]:
    return [
        _component("cheap prefilter/ranking", "deterministic ranking/triage", "bot/strategy_engine.py::_cheap_prefilter_candidate", "StrategyEngine.run_cycle", [], "analyze_only", ["precision/reject history not part of ranking"], "partial"),
        _component("DeepSeek preprocess", "LLM dossier compression", "bot/strategy_engine.py::_run_deepseek_preprocess", "run_cycle selected_for_gate", ["DeepSeekClient.json_chat"], "analyze_only", ["usually disabled fallback; no product rules schema"], "partial"),
        _component("GPT nano entry gate", "LLM fast gate", "bot/strategy_engine.py::_run_entry_gate", "run_cycle selected_for_gate", ["ResilientLLMClient.json_response"], "analyze_only", ["allowed setup types only four values"], "ok"),
        _component("analyst stack", "LLM regime/trend/breakout/meanrev/bull/bear/synth", "bot/strategy_engine.py::_run_full_analysis_stack", "selected_for_full", ["REGIME/TREND/BREAKOUT/MEANREV/BULL/BEAR/SYNTH prompts"], "analyze_only", ["product rules and reject reasons not explicit prompt fields"], "partial"),
        _component("trade planner", "LLM structured plan proposer", "bot/strategy_engine.py::_run_trade_planner_with_fallback", "_run_full_analysis_stack", ["bot.trade_planner.normalize_trade_plan"], "plan", ["min order/precision not explicit schema fields"], "partial"),
        _component("final judge", "LLM final judge", "bot/strategy_engine.py::_judge_with_fallback", "_run_full_analysis_stack", ["ResilientLLMClient", "Anthropic fallback"], "judge", ["does not receive recent Coinbase precision reject reasons as named context"], "partial"),
        _component("objective trade score POC", "deterministic report-only scorer", "bot/objective_trade_score.py", "tools/show_objective_trade_score_audit.py", [], "audit_only", ["not integrated into planner/judge yet"], "partial"),
        _component("opportunity memory POC", "report-only near-miss memory", "bot/opportunity_memory.py", "tools/show_opportunity_memory_status.py", [], "audit_only", ["parallel to pending_trade_plans; not primary promotion route"], "partial", state=["state/opportunity_memory.json when explicit tool persist/upsert used"]),
        _component("pending trade plans", "integrated future watch/promotion memory", "bot/pending_trade_plans.py", "StrategyEngine._maybe_store_pending_trade_plan", ["evaluate_ticker", "store_plan"], "plan", ["stores only prepare_* plans above confidence threshold"], "ok", state=["state/pending_trade_plans.json"]),
        _component("paper pending order intents", "paper/watchlist pending intent memory", "bot/pending_order_intents.py", "StrategyEngine._maybe_store_paper_pending_order_intent", [], "plan", ["paper-route, not live order authority"], "ok", state=["state/pending_order_intents.json"]),
        _component("orderbook entry planner", "deterministic resting limit preview", "bot/orderbook_entry_planner.py", "execution planner / Phase C43", [], "execute_preview", ["product precision handled later by submitter not planner"], "ok"),
        _component("read-only execution planner", "LLM execution-tactics advisor", "bot/execution_planner.py", "StrategyEngine._maybe_run_read_only_execution_planner", ["orderbook_analyzer", "orderbook_entry_planner"], "execute_preview", ["read-only; not a gate by itself"], "ok", logs=["logs/execution_plans.jsonl"]),
        _component("Phase C live guard", "deterministic live-entry safety gate", "bot/phase_c_live_guard.py", "Phase C43 preparation", [], "execute_preview", ["can block; no live submit alone"], "ok"),
        _component("Phase C submitter", "deterministic Coinbase payload/submit adapter", "bot/phase_c_live_submitter.py", "Phase C43 preparation", ["CoinbaseClient when armed"], "execute_live", ["P0 runtime deployment must prove precision rules present before submit"], "partial", input_context={"precision_rules": True, "min_order_rules": True}, logs=["logs/phase_c_live_submit.jsonl"]),
        _component("Phase C43 lifecycle service", "entry lifecycle polling/apply scaffold", "bot/phase_c43_lifecycle_service.py", "run_trader_loop lifecycle hook", ["OrderStore", "D2/D3 builders"], "execute_preview", ["local apply requires explicit config/evidence"], "ok", logs=["logs/phase_c43_lifecycle_service.jsonl"]),
        _component("D2/D3 exit planner/lifecycle", "position plan and controlled limit SELL exits", "bot/phase_d3_open_exit_lifecycle_manager.py", "Phase C43 lifecycle", ["OrderStore"], "execute_preview", ["must keep exchange order id/fill evidence rails"], "ok"),
        _component("controlled stop exit plan", "Mode B market stop route preview/apply gate", "bot/controlled_stop_market_exit_plan.py", "protective watcher / D3 lifecycle", [], "execute_preview", ["Mode B apply separately ACK-gated"], "ok"),
        _component("trailing stop manager", "report/preview trailing management", "bot/trailing_stop_manager.py", "tools/show_trailing_stop_status.py", [], "audit_only", ["not integrated as autonomous cancel/replace apply"], "partial"),
        _component("market intelligence context", "external macro/liquidity context injector", "bot/market_intelligence_context.py", "StrategyEngine._inject_market_intelligence_context", [], "analyze_only", ["can be stale; no hard authority"], "ok"),
        _component("neural shadow context", "shadow-only learning context", "bot/neural_shadow_policy.py", "StrategyEngine._inject_neural_shadow_context", [], "analyze_only", ["one-class no-trade bias explicitly soft only"], "ok"),
        _component("live learning/backlearning", "report-only learning context", "bot/live_learning_orchestrator.py", "StrategyEngine._refresh_live_learning_context", [], "analyze_only", ["no direct learning-to-execution bridge"], "ok"),
        _component("adaptive parameter governor", "bounded report/activation planning", "bot/autonomous_parameter_governor.py", "tools/run_autonomous_parameter_governor.py", [], "audit_only", ["approved profile activation still ACK/hash gated"], "ok"),
        _component("reflection/adaptive policy lab", "learning/report lab", "bot/adaptive_policy_lab.py", "tools/write_adaptive_policy_audit.py", [], "audit_only", ["not direct execution"], "ok"),
    ]


def build_context_findings(root: str | Path = ".") -> dict[str, Any]:
    matrix = build_context_matrix(root)
    top20 = [
        "product_rules exist in submitter/product tools but are not consistently named in planner/final judge context",
        "recent Coinbase rejection reasons are logged but not summarized into planner/final judge decision_context",
        "reward_to_fee exists in orderbook preview but is not a required final judge input",
        "reward_to_risk exists in orderbook preview but is not a required final judge input",
        "opportunity_memory exists but pending_trade_plans are the integrated promotion route",
        "orderbook imbalance/depth is used by execution planning more than strategic LLM scoring",
        "market intelligence can be injected but stale status is not a deterministic blocker",
        "neural shadow context is present but intentionally non-authoritative",
        "ATR exists but ATR percentile/regime is absent",
        "EMA20/50/200 exist but EMA8/21 setup language is absent",
        "Bollinger squeeze exists but Keltner squeeze is absent",
        "RSI exists but divergence detection is absent",
        "VWAP reclaim is absent",
        "volume_vs_avg exists but volume z-score is absent",
        "watch_memory exists but is simpler than opportunity objects with trigger/invalidation hashes",
        "last failed submit reason is not part of cheap prefilter",
        "precision feasibility is checked late in submitter instead of scored before judge",
        "partial fill lifecycle exists for exits but entry partial-fill decision reporting remains a P1 proof area",
        "trailing stop is preview/status, not autonomous cancel-replace",
        "setup expiry exists in planner schema but is not consistently populated",
    ]
    return {"matrix": matrix, "top_20_underused_information": top20}


def build_open_source_pattern_report() -> dict[str, Any]:
    rows = [
        ("strategy lifecycle", "present", "strategy file with entry/exit/ROI/stop callbacks", "strategy plus connector/executor split", "strategy methods with simple order syntax", "Algorithm lifecycle and event handlers", "Document current Mode A/B lifecycle as canonical.", "P3"),
        ("signal generation", "present", "populate indicators and entry/exit signals", "controllers/scripts generate proposals", "should_long/should_short and filters", "Alpha/Insight-style separation", "Keep LLM strategy + deterministic gates separation.", "P2"),
        ("multi-timeframe context", "present", "informative pairs/timeframes", "candles feed/controller data", "multi timeframe/symbol support", "consolidators/history", "Add schema tests for MTF fields to prompts.", "P2"),
        ("indicators", "partial", "TA-Lib/pandas-ta rich set", "strategy-defined indicators", "300+ indicator library", "large indicator catalog", "Add only missing high-value features: VWAP, EMA8/21, ATR percentile.", "P2"),
        ("setup abstraction", "partial", "strategy-specific", "controller/executor pattern", "strategy class methods", "Alpha models", "Use setup_pattern_library POC as taxonomy.", "P1"),
        ("hyperparameter optimization", "partial", "Hyperopt", "research notebooks/scripts", "Optuna optimization", "optimization/backtesting", "Keep ACK-gated profile activation.", "P2"),
        ("dry-run/live split", "present", "dry/live modes", "paper/live connectors", "backtest/paper/live", "backtest/paper/live brokerage models", "No change.", "P0"),
        ("connector abstraction", "partial", "exchange abstraction", "many standardized connectors", "exchange drivers", "brokerage models", "Centralize Coinbase rules/reject normalization.", "P1"),
        ("order lifecycle", "partial", "order tracking", "connector order tracker", "partial fills/orders", "OrderEvent callbacks", "Normalize Coinbase events for entry/D3.", "P1"),
        ("partial fills", "partial", "trade/order status", "connector events", "supports partial fills", "OrderEvent fill quantity/status", "Add entry partial-fill fixture audit.", "P1"),
        ("precision/min-order", "partial", "exchange precision handling", "trading rules in connectors", "exchange filters", "symbol properties/brokerage models", "P0: prove precision/min-order in live submit context.", "P0"),
        ("trailing stoploss", "preview_only", "trailing stop with offset", "controller/executor stops", "stop_loss helpers", "trailing stop order type/models", "Keep Mode B ACK; add D4 cancel-first tests.", "P1"),
        ("position accounting", "present", "Trade object", "inventory/order tracker", "position object", "Portfolio/Securities holdings", "No local apply without evidence.", "P0"),
        ("risk management", "present", "stake/stoploss/pairlocks", "budget/checker", "risk helpers", "risk management models", "Keep caps 100/3/3/1 and default quote 50.", "P0"),
        ("pair ranking", "present", "pairlists", "market selectors", "routes", "universes", "Improve audit by setup-type/rank.", "P2"),
        ("opportunity memory", "partial", "custom state/pair locks possible", "controller state", "strategy vars/alerts", "scheduled universes/insights", "Promote POC into pending plan context only after tests.", "P1"),
        ("backtesting/walk-forward", "partial", "first-class backtest/hyperopt", "paper/simulation", "backtest/benchmark/Monte Carlo", "backtest/research", "Require OOS for parameter profile ACK.", "P2"),
        ("audit/dashboard/status", "partial", "FreqUI/API", "CLI/dashboard", "web/debug logs", "statistics/results", "Consolidate latest audits and stale-window warnings.", "P3"),
    ]
    keys = ["feature", "our_status", "freqtrade_pattern", "hummingbot_pattern", "jesse_pattern", "lean_or_other_pattern", "gap", "priority"]
    return {
        "sources": [
            "https://www.freqtrade.io/en/stable/strategy-customization/",
            "https://www.freqtrade.io/en/stable/stoploss/",
            "https://raw.githubusercontent.com/hummingbot/hummingbot/master/README.md",
            "https://raw.githubusercontent.com/jesse-ai/jesse/master/README.md",
            "https://www.quantconnect.com/docs/v2/writing-algorithms/trading-and-orders/order-events",
        ],
        "matrix": [
            {**dict(zip(keys, row)), "recommended_poc": row[6], "license_notes": "Pattern-only comparison; no code copied.", "copy_code": False}
            for row in rows
        ],
    }


def build_best_practice_rows() -> list[dict[str, str]]:
    return [
        {"source": "Freqtrade stoploss docs", "best_practice": "Trailing stops should ratchet from highest observed price and can use activation offsets.", "our_current_status": "preview_only", "gap": "D4 trailing manager is not autonomous apply.", "recommended_change": "Keep preview; add cancel-first D4 replacement proof before Mode B.", "test_needed": "trailing never lowers stop; stale TP block", "priority": "P1"},
        {"source": "QuantConnect Order Events docs", "best_practice": "Order lifecycle should consume status/fill events including partial fills.", "our_current_status": "partial", "gap": "Polling exists; normalized event abstraction incomplete.", "recommended_change": "Add Coinbase event normalizer fixtures.", "test_needed": "partial/fill/cancel/reject events", "priority": "P1"},
        {"source": "Hummingbot connector pattern", "best_practice": "Strategy logic should be separated from connector trading rules.", "our_current_status": "partial", "gap": "Product rules are late submitter context, not full judge context.", "recommended_change": "Inject product_rules summary into feature_pack decision_context.", "test_needed": "judge context contains increments/mins", "priority": "P0"},
        {"source": "Jesse README", "best_practice": "Research/backtest/optimize/live modes and Monte Carlo help avoid overfitting.", "our_current_status": "partial", "gap": "Profile ACK requires evidence but setup taxonomy lacks walk-forward score.", "recommended_change": "Add setup-level OOS metrics before profile activation.", "test_needed": "report-only setup OOS matrix", "priority": "P2"},
    ]


def build_report(root: str | Path = ".") -> dict[str, Any]:
    context = build_context_findings(root)
    setup = build_setup_pattern_status()
    return {
        "phase": "agent_workflow_information_audit_v1",
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "agent_map": build_agent_map(),
        "context_completeness_matrix": context["matrix"],
        "top_20_underused_information": context["top_20_underused_information"],
        "setup_pattern_summary": setup["summary"],
        "setup_pattern_matrix": setup["matrix"],
        "near_miss_route": {
            "integrated_route": "wait/prepare_* -> pending_trade_plans or paper_pending_order_intents -> trigger_ready promotion -> fresh full analysis -> final judge -> orderbook planner -> Phase C guard/submitter",
            "opportunity_memory_status": "report_only_parallel_poc",
            "live_order_authority": False,
        },
        "prompt_schema_review": {
            "prompt_files": ["bot/prompts.py", "bot/strategy_engine.py", "bot/trade_planner.py"],
            "strict_json": True,
            "schema_failures_logged": True,
            "fallbacks": ["safe wait/no_plan", "anthropic fallback when enabled", "deterministic starter probe fallback"],
            "missing_fields": ["product_precision", "min_order_rules", "last_failed_submit_reason", "normalized reward_to_fee", "normalized reward_to_risk"],
        },
        "best_practices": build_best_practice_rows(),
        "readiness": "STATUS B: Agent workflow works but important context gaps remain before trusting decisions.",
        "rails": {"DEFAULT_QUOTE_SIZE_USDC": "50 expected from config/audit", "caps_100_3_3_1_intact": True},
        "live_side_effects": False,
    }


def build_backlog(report: dict[str, Any]) -> dict[str, Any]:
    items = [
        {"priority": "P0", "title": "Inject product precision/min-order/recent reject reasons into planner and final judge context", "risk": "LLM can approve plans that submitter later rejects for precision/min size.", "recommended_action": "Add feature_pack decision_context summary and tests; keep submitter fail-closed."},
        {"priority": "P1", "title": "Normalize reward-to-risk and reward-to-fee before final judge", "risk": "Ratios affect deterministic planner but not consistently LLM scoring.", "recommended_action": "Add numeric context fields and schema tests."},
        {"priority": "P1", "title": "Unify opportunity_memory POC with pending_trade_plans only after tests", "risk": "Parallel memory can confuse operator if not canonical.", "recommended_action": "Keep pending_trade_plans primary; opportunity_memory report-only until integration tests pass."},
        {"priority": "P1", "title": "Add Coinbase order event normalizer fixtures", "risk": "Partial/reject/cancel lifecycle proof remains scattered.", "recommended_action": "Fixture partial fill, reject, cancel, filled snapshots."},
        {"priority": "P2", "title": "Add VWAP/EMA8/21/ATR percentile/volume z-score POC fields", "risk": "Setups are good but missing common context features.", "recommended_action": "Report-only feature engineering first, then prompt context if useful."},
    ]
    return {"read_only": True, "coinbase_call_attempted": False, "items": items, "status": report["readiness"]}


def _md(report: dict[str, Any]) -> str:
    lines = [
        "# Agent Workflow Information Audit",
        "",
        report["readiness"],
        "",
        "## Agent Map",
    ]
    for row in report["agent_map"]:
        lines.append(f"- `{row['status']}` {row['agent_or_component']}: {row['role']} ({row['decision_authority']}); gaps={'; '.join(row['gaps']) or 'none'}")
    lines.extend(["", "## P0/P1 Context Gaps"])
    for row in report["context_completeness_matrix"]:
        if row["priority"] in {"P0", "P1"}:
            lines.append(f"- `{row['priority']}` {row['context_field']}: judge={row['available_to_final_judge']} submitter={row['available_to_submitter']} fix={row['recommended_fix']}")
    lines.extend(["", "## Underused Information"])
    lines.extend(f"- {item}" for item in report["top_20_underused_information"])
    lines.extend(["", "## Near Miss Route", f"- {report['near_miss_route']['integrated_route']}"])
    lines.extend(["", "## Best Practices"])
    for row in report["best_practices"]:
        lines.append(f"- `{row['priority']}` {row['source']}: {row['recommended_change']}")
    return "\n".join(lines) + "\n"


def _oss_md(report: dict[str, Any]) -> str:
    lines = ["# Open Source Agent Pattern Comparison", "", "Pattern-level comparison only; no source code copied.", "", "## Sources"]
    lines.extend(f"- {src}" for src in report["sources"])
    lines.extend(["", "## Matrix"])
    for row in report["matrix"]:
        lines.append(f"- `{row['priority']}` {row['feature']}: ours={row['our_status']}; gap={row['gap']}")
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build agent workflow information audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_report(args.root)
    atomic_write_json(args.json_out, report)
    atomic_write_text(args.md_out, _md(report))
    backlog = build_backlog(report)
    atomic_write_json(BACKLOG_JSON, backlog)
    atomic_write_text(BACKLOG_MD, "\n".join(["# Agent Workflow Hardening Backlog", ""] + [f"- `{x['priority']}` {x['title']}: {x['risk']}" for x in backlog["items"]]) + "\n")
    oss = build_open_source_pattern_report()
    atomic_write_json(OSS_JSON, oss)
    atomic_write_text(OSS_MD, _oss_md(oss))
    print(json.dumps({"json_out": args.json_out, "md_out": args.md_out, "agents": len(report["agent_map"]), "status": report["readiness"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
