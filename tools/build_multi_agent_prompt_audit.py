#!/usr/bin/env python3
"""Read-only multi-agent pipeline + prompt audit.

Builds reports/audits/multi-agent-prompt-audit-latest.{json,md}. Combines:

1. A curated, file:line-cited call-graph of every decision-pipeline layer
   (hard gate, DeepSeek gate, analyst modules, planner, judge, deterministic
   risk layer, C4.3 entry, D3 exit/lifecycle, reflection/outcome stores,
   GrowBot/River). This was derived from a manual code-reading pass over
   bot/strategy_engine.py and bot/run_trader_loop.py and is recorded here as
   a structured dataset rather than re-derived at runtime (the call graph
   does not change between runs; the *config flags* that gate it do, so
   those are read live).
2. A live read of the relevant on/off flags from the process environment
   (mirrors bot/config.py's own env-var names and defaults, but never
   imports bot.config / instantiates BotConfig -- that requires a live
   OPENAI_API_KEY and is unnecessary for a static-shape audit).
3. A prompt inventory parsed straight from bot/prompts.py via `ast` (no
   `import bot.prompts`, no execution).
4. A few cheap dynamic safety checks (no secret-shaped strings in prompt
   templates; no `api_key` reference inside the payload-construction
   modules outside of client-constructor lines).

No Coinbase calls, no state writes, no LLM calls, no service restarts.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# 1. Curated layer call-graph (manual code-reading pass, file:line cited)
# ---------------------------------------------------------------------------

LAYERS: List[Dict[str, Any]] = [
    {
        "name": "cheap_prefilter",
        "label": "Hard gate (deterministic prefilter)",
        "is_llm": False,
        "invoked_from": "bot/strategy_engine.py:7228 (_cheap_prefilter_candidate, def bot/strategy_engine.py:3966)",
        "input_shape": "feature_pack (market/indicators/structure/microstructure), breadth_context, watch_memory",
        "prompt": None,
        "output_shape": "prefilter dict: prefilter_score, prefilter_decision, setup_guess, reasons, warnings",
        "forwarded_to": "ranking -> entry gate selection (gated_rows)",
        "logged_to": "watch memory only (no analysis.jsonl row for non-selected candidates)",
        "skip_conditions": "candidates ranked below max_candidates_for_deepseek_gate never reach any LLM layer",
        "skip_reason_code": "_build_gate_only_skip_result (bot/strategy_engine.py:7265)",
    },
    {
        "name": "hard_risk_gate",
        "label": "Deterministic risk layer",
        "is_llm": False,
        "invoked_from": "bot/strategy_engine.py:6055 and :6115 inside maybe_execute (_hard_risk_gate def bot/strategy_engine.py:5946)",
        "input_shape": "ticker, judge, feature_pack.risk_context.engine_state, feature_pack.market, size_quote, existing_position",
        "prompt": None,
        "output_shape": "list[str] hard_rejects (empty = pass)",
        "forwarded_to": "maybe_execute -> execution.jsonl (status=rejected if non-empty)",
        "logged_to": "logs/execution.jsonl",
        "skip_conditions": "judge decision in {wait, reject, no_trade} short-circuits before the gate runs",
        "skip_reason_code": "bot/strategy_engine.py:5976",
    },
    {
        "name": "deepseek_gate",
        "label": "DeepSeek preprocess (cheap LLM pre-filter)",
        "is_llm": True,
        "provider": "deepseek",
        "model_config_var": "deepseek_model",
        "invoked_from": "bot/strategy_engine.py:7282 (_run_deepseek_preprocess, def :3548) -> client call bot/llm_clients.py DeepSeekClient.json_chat (call site bot/strategy_engine.py:3573)",
        "input_shape": "entire feature_pack (no pruning)",
        "prompt": "DEEPSEEK_PREPROCESS_PROMPT (bot/prompts.py)",
        "output_shape": "deepseek_pack: regime_hints, trend_hints, breakout_hints, meanrev_hints, risk_hints, concise_evidence, raw_pattern_hints, news_sentiment_hints, uncertainties",
        "forwarded_to": "entry gate input, dossier for all 6 analysts + synth + planner + judge",
        "logged_to": "logs/llm_raw.jsonl + logs/analysis.jsonl (as deepseek_pack field)",
        "skip_conditions": "disabled by default (ENABLE_DEEPSEEK_PREPROCESS=false default) -- self.deepseek is None, fallback dict returned with no API call",
        "skip_reason_code": "fallback_reason=deepseek_preprocess_disabled_gpt_nano_gate_primary (bot/strategy_engine.py:3553-3570)",
        "enabled_flag_env": "ENABLE_DEEPSEEK_PREPROCESS",
        "enabled_flag_default": False,
    },
    {
        "name": "entry_gate",
        "label": "Entry gate (cheap nano LLM filter, the real 'hard gate' before expensive analysis)",
        "is_llm": True,
        "provider": "openai",
        "model_config_var": "entry_gate_model (hardcoded gpt-5.4-nano, bot/strategy_engine.py:84,303)",
        "invoked_from": "bot/strategy_engine.py:7283 (_run_entry_gate, def :1912) -> client call bot/strategy_engine.py:1934",
        "input_shape": "feature_pack, deepseek_pack, task{objective, allowed_setup_types, allowed_decisions, high_recall}",
        "prompt": "GPT_NANO_GATE_PROMPT (bot/prompts.py)",
        "output_shape": "decision in {skip,watch,analyze,priority_analyze}, priority, setup_type, confidence, reasons, warnings",
        "forwarded_to": "feature_pack.entry_gate, feature_pack.risk_context.entry_gate, gated_rows row; only analyze/priority_analyze promoted to full analysis",
        "logged_to": "logs/llm_raw.jsonl; analysis.jsonl for promoted rows; _build_skip_analysis_result for the rest",
        "skip_conditions": "candidates beyond max_candidates_for_deepseek_gate never gated; existing open positions bypass entirely (decision=position_management_bypass, bot/strategy_engine.py:3934-3945)",
        "skip_reason_code": "position_management_bypass / not in top-N ranking",
    },
    {
        "name": "analyst_modules",
        "label": "Analyse-agent (6 archetype modules + synth)",
        "is_llm": True,
        "provider": "openai",
        "model_config_var": "openai_analyst_model (default gpt-5.4-mini)",
        "invoked_from": "bot/strategy_engine.py:3735-3742 inside _run_full_analysis_stack (def :3711), each via _safe_module_response (def :2747, call :2755)",
        "input_shape": "dossier: feature_pack, deepseek_pack, chart_patterns, recent_reflections, decision_outcomes, pending_trade_plan (synth additionally gets the other 6 outputs)",
        "prompt": "REGIME_PROMPT / TREND_PROMPT / BREAKOUT_PROMPT / MEANREV_PROMPT / BULL_PROMPT / BEAR_PROMPT / SYNTH_PROMPT (bot/prompts.py)",
        "output_shape": "module-specific dict (or {fallback:true,...} on error)",
        "forwarded_to": "result dict -> trade planner input, judge input, analysis.jsonl",
        "logged_to": "logs/analysis.jsonl",
        "skip_conditions": "whole stack only runs for tickers promoted by the entry gate (analyze/priority_analyze); once promoted, all 7 module calls run unconditionally (no per-module skip)",
        "skip_reason_code": "n/a (entry-gate decision is the only gate)",
    },
    {
        "name": "trade_planner",
        "label": "D2-style entry trade planner (pre-judge LLM planner)",
        "is_llm": True,
        "provider": "openai",
        "model_config_var": "openai_trade_planner_model (default gpt-5.5)",
        "invoked_from": "bot/strategy_engine.py:3792 inside _run_full_analysis_stack, only inside `if should_call_judge:` (def _run_trade_planner_with_fallback :3059, call :3073)",
        "input_shape": "planner_input: ticker, feature_pack, deepseek_pack, chart_patterns, 6 analyst outputs + synth, existing_position, recent_reflections, decision_outcomes, pending_trade_plan",
        "prompt": "TRADE_PLANNER_PROMPT (bot/prompts.py)",
        "output_shape": "trade_plan: plan_action, max_quote_size/size_quote, preferred_limit_price/entry_price, plan_type, setup_type, valid_trade_plan",
        "forwarded_to": "judge_input, execution_feasibility",
        "logged_to": "logs/analysis.jsonl (as trade_plan field)",
        "skip_conditions": "skipped when _should_call_expensive_judge (def :2790) returns False -- builds deterministic build_default_no_plan instead",
        "skip_reason_code": "source=trade_planner_skipped_by_expensive_judge_gate (bot/strategy_engine.py:3859)",
    },
    {
        "name": "final_judge",
        "label": "Final judge",
        "is_llm": True,
        "provider": "openai (primary), anthropic (fallback, default disabled)",
        "model_config_var": "openai_judge_model (default gpt-5.5); anthropic_model (default claude-opus-4-6) fallback only",
        "invoked_from": "bot/strategy_engine.py:3820 inside _run_full_analysis_stack (def _judge_with_fallback :3134); primary call :3288, anthropic fallback :3308",
        "input_shape": "judge_base_input: dossier + all module outputs + synth + existing_position + trade_plan + product rules",
        "prompt": "CLAUDE_JUDGE_PROMPT (bot/prompts.py) -- name is historical, primary model is OpenAI gpt-5.5",
        "output_shape": "decision in {approve_trade,wait,reject,no_trade,reduce_size,close_position}, side, size_quote, confidence, setup_type, position_action, valid_trade_plan, reasons, score fields",
        "forwarded_to": "analysis['judge'] -> maybe_execute / _handle_position_action -> hard risk gate -> C4.3 / D3",
        "logged_to": "logs/analysis.jsonl; state/decision_outcomes.json via _record_decision_outcome_snapshot (bot/strategy_engine.py:7408)",
        "skip_conditions": "gated by _should_call_expensive_judge (bot/strategy_engine.py:2790): always called for open positions or when ENABLE_EXPENSIVE_JUDGE_GATE=false; for new entries requires constructive gate/synth/bull confidence thresholds",
        "skip_reason_code": "_build_expensive_judge_skipped_result (bot/strategy_engine.py:3022), judge_skip_reason field (bot/strategy_engine.py:3872-3883)",
        "enabled_flag_env": "ENABLE_EXPENSIVE_JUDGE_GATE",
        "enabled_flag_default": True,
    },
    {
        "name": "position_watch",
        "label": "Open-position heartbeat watch (nano LLM, escalation-only)",
        "is_llm": True,
        "provider": "openai",
        "model_config_var": "position_watch_model (hardcoded gpt-5.4-nano)",
        "invoked_from": "bot/strategy_engine.py:5900 (_run_position_watch, def :5885), called from _run_open_position_hourly_check (:7099) only on a deterministic warning from _position_heartbeat_prefilter (:5719)",
        "input_shape": "position dict + entire feature_pack",
        "prompt": "GPT_NANO_POSITION_WATCH_PROMPT (bot/prompts.py)",
        "output_shape": "watch verdict; only true escalation re-runs the full analyst+judge stack (analyze_ticker, :6983)",
        "forwarded_to": "escalation -> full analysis stack for that ticker",
        "logged_to": "logs/llm_raw.jsonl",
        "skip_conditions": "only runs when the deterministic prefilter flags a warning; most heartbeat ticks never call this",
        "skip_reason_code": "deterministic prefilter returned no warning",
    },
    {
        "name": "d2_planner",
        "label": "D2 position executor (deterministic exit/lifecycle planner)",
        "is_llm": False,
        "invoked_from": "bot/phase_d2_position_executor.py build_phase_d2_position_executor_report, driven by bot/phase_c43_lifecycle_orchestrator.py (import :17) inside the post-cycle lifecycle service hook",
        "input_shape": "open C4.3 entry orders / open positions, product rules",
        "prompt": None,
        "output_shape": "D2 plan (status incl. D2_PLAN_STATUS_READY)",
        "forwarded_to": "lifecycle service persistence (preview-only unless explicitly enabled)",
        "logged_to": "logs/phase_c43_lifecycle_service.jsonl",
        "skip_conditions": "disabled when enable_phase_c43_lifecycle_orchestrator is False",
        "skip_reason_code": "n/a",
    },
    {
        "name": "c43_entry",
        "label": "C4.3 autonomous live entry (deterministic order construction + guarded submit)",
        "is_llm": False,
        "invoked_from": "bot/strategy_engine.py:5469 (_maybe_process_phase_c43_live_entry_plan, def :5074) -> bot/phase_c43_autonomous_entry_live.py build_phase_c43_guard_and_submit_preparation (:5171)",
        "input_shape": "execution_plan (read-only), judge decision/side, order_intent",
        "prompt": None,
        "output_shape": "status, live_submission_attempted, live_order_submitted, submit_result.payload.client_order_id",
        "forwarded_to": "state/open_orders.json (OrderStore) for lifecycle reconciliation",
        "logged_to": "logs/phase_c_live_submit.jsonl",
        "skip_conditions": "skipped when existing position present, execution_plan invalid, judge decision != approve_trade/BUY, or order intent not actionable; live submit additionally requires the full autonomous_runtime_enabled flag chain (bot/strategy_engine.py:5141-5163)",
        "skip_reason_code": "early-return None at bot/strategy_engine.py:5102/5104/5110/5127",
    },
    {
        "name": "d3_exit",
        "label": "D3 controlled live exit / lifecycle",
        "is_llm": False,
        "invoked_from": "bot/strategy_engine.py:6730 (_maybe_route_full_workflow_position_exit_to_d3, def :6460) and via the lifecycle service hook (bot/phase_c43_lifecycle_orchestrator.py import :18)",
        "input_shape": "open position, exit intent",
        "prompt": None,
        "output_shape": "phase_d3 controlled exit report",
        "forwarded_to": "OrderStore / StateStore reconciliation",
        "logged_to": "logs/phase_c43_lifecycle_service.jsonl; D3-specific exit logs",
        "skip_conditions": "blocked unless ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT and phase_d3_runtime_submit_ack == D3_ACK; paper mode simulates instead of routing to D3",
        "skip_reason_code": "status=d3_controlled_exit_blocked_by_policy (bot/strategy_engine.py:6743)",
    },
    {
        "name": "lifecycle_service_hook",
        "label": "Post-cycle lifecycle service (independent order/position watch)",
        "is_llm": False,
        "invoked_from": "run_trader_loop.py:1098 (_run_lifecycle_orchestrator_service_hook, def :1081), runs after every full cycle (:1172) AND every heartbeat cycle (:1197) -- so it runs even when the entry-scan path is cheap/skipped",
        "input_shape": "open C4.3 entry orders, open exit orders, governance state",
        "prompt": None,
        "output_shape": "lifecycle service report",
        "forwarded_to": "OrderStore/StateStore reconciliation (preview-only by default)",
        "logged_to": "logs/phase_c43_lifecycle_service.jsonl",
        "skip_conditions": "skipped entirely when enable_phase_c43_lifecycle_orchestrator is False",
        "skip_reason_code": "n/a",
    },
    {
        "name": "reflection_outcome_layer",
        "label": "Reflection / decision-outcome / execution-outcome stores",
        "is_llm": False,
        "invoked_from": "_record_decision_outcome_snapshot (bot/strategy_engine.py:724, called :7408/:5578/:7147); _record_trade_reflection (bot/strategy_engine.py:838, called on position close :6688); ExecutionOutcomeTracker (bot/strategy_engine.py:320-322)",
        "input_shape": "judge decision + outcome context (no LLM call -- trade_reflection.py builds deterministic records)",
        "prompt": None,
        "output_shape": "decision_outcome record / trade_reflection record / execution_outcome record",
        "forwarded_to": "state/decision_outcomes.json, state/trade_reflections.jsonl, logs/execution_outcomes.jsonl; summaries re-injected into the next cycle's analyst dossier",
        "logged_to": "state/decision_outcomes.json, state/trade_reflections.jsonl, logs/execution_outcomes.jsonl",
        "skip_conditions": "decision-outcome recording happens for every analyzed ticker; trade reflection only fires on an actual position close",
        "skip_reason_code": "n/a",
    },
    {
        "name": "growbot_river_learning",
        "label": "GrowBot/River learning layer",
        "is_llm": False,
        "invoked_from": "NOT in the live cycle -- bot/growbot_learning_adapter.py / bot/river_online_parameter_learner.py are only imported by bot/growbot_historical_replay.py and the offline sidecar/replay tools. The live cycle only touches the soft aggregator bot/live_learning_orchestrator.py run_live_learning_maintenance() via _refresh_live_learning_context (bot/strategy_engine.py:500, called :7159)",
        "input_shape": "state/decision_outcomes.json, reflections",
        "prompt": None,
        "output_shape": "runtime_context: lessons, parameter *suggestions*, parameter_mutation_allowed=False",
        "forwarded_to": "feature_pack.decision_context.live_learning, read by analysts/judge as context only -- never mutates parameters or places orders",
        "logged_to": "reports/growbot_river/*, reports/learning/*",
        "skip_conditions": "soft context always computed once per cycle; the offline GrowBot/River learning cycle itself only runs when tools/run_growbot_river_learning_cycle.py is invoked out-of-band",
        "skip_reason_code": "n/a",
    },
]

DUPLICATE_CONTEXT_FINDING = {
    "finding": "duplicate_context_across_layers",
    "severity": "primary_cost_driver",
    "description": (
        "The same full feature_pack (raw OHLC slices for 4 timeframes, microstructure, "
        "orderbook_context, structure, indicators, sentiment, news_context) is serialized "
        "and re-sent, unpruned, to at minimum: deepseek_preprocess, all 6 analyst modules, "
        "synth, trade_planner, final_judge, and position_watch (when an open position "
        "exists) -- 8-10+ full re-serializations of the same payload per ticker per cycle. "
        "compact_payload_for_llm() (bot/llm_clients.py:200) only shortens very long "
        "individual strings; it never drops keys or prunes candle/orderbook arrays. There "
        "is no delta/summary substitution between layers and no caching anywhere "
        "(grep for lru_cache/memoize/cache_key/prompt_cache across the LLM call chain "
        "returns zero hits)."
    ),
    "file_refs": [
        "bot/strategy_engine.py:3575 (deepseek preprocess payload)",
        "bot/strategy_engine.py:3726-3733 (dossier sent to all 6 analysts + synth)",
        "bot/strategy_engine.py:3775 / bot/trade_planner.py:700-702 (planner input)",
        "bot/strategy_engine.py:3814 (judge input)",
        "bot/strategy_engine.py:5705 (position watch payload)",
        "bot/llm_clients.py:200-221 (compact_payload_for_llm does not prune keys)",
        "bot/market_data.py:432-561 (feature_pack raw_context/microstructure/orderbook size)",
    ],
}

RETRY_REBILLING_FINDING = {
    "finding": "retries_rebill_the_provider",
    "severity": "secondary_cost_driver",
    "description": (
        "bot/llm_clients.py wraps every provider call in `for attempt in range(max_retries)` "
        "(default max_retries=3) with a 1.5s*(attempt+1) backoff. A malformed-JSON response "
        "triggers a fresh, fully-billable retry (up to 3x per logical call). Billing/credit "
        "errors short-circuit immediately and do not retry, but corrupt-output retries do "
        "re-bill. The cost ledger built in this audit counts attempts (not just final-success "
        "calls) for exactly this reason."
    ),
    "file_refs": [
        "bot/llm_clients.py:570 (OpenAI json_response retry loop)",
        "bot/llm_clients.py:659 (Anthropic json_message retry loop)",
        "bot/llm_clients.py:764 (DeepSeek json_chat retry loop)",
    ],
}

NO_DUPLICATE_TICKER_PASS_FINDING = {
    "finding": "no_duplicate_full_pass_per_ticker_per_cycle",
    "severity": "info",
    "description": (
        "A ticker cannot be analyzed by both the existing-position loop and the new-entry "
        "loop in the same run_cycle() -- processed_tickers (set in the existing-position "
        "loop) is explicitly excluded from the new-entry universe. Within one full analysis "
        "pass, each analyst module and the judge run at most once. The one legitimate "
        "cross-cycle overlap: an open position can get a full analyst+judge pass from an "
        "hourly heartbeat escalation AND again from the next full-cycle boundary within the "
        "same clock hour -- not a bug, but worth knowing when reading 'calls per ticker per "
        "hour' rather than 'per cycle'."
    ),
    "file_refs": [
        "bot/strategy_engine.py:7201,7204 (processed_tickers populated in existing-position loop)",
        "bot/strategy_engine.py:7206-7209 (new-entry universe excludes processed_tickers)",
    ],
}

OPEN_POSITION_WATCH_FINDING = {
    "finding": "open_positions_monitored_independently_of_opportunity_scan",
    "severity": "info",
    "description": (
        "Open positions/orders are watched on three independent tracks, none of which "
        "depend on the new-entry opportunity scan running or being expensive: (1) the "
        "existing-position loop inside run_cycle() itself, (2) the hourly heartbeat cycle "
        "(run_position_heartbeat_cycle), which only scans open-position tickers, and (3) "
        "the post-cycle lifecycle service hook, which runs after both full cycles and "
        "heartbeat cycles. So a cheap/skipped entry-scan cycle never leaves open positions "
        "unwatched."
    ),
    "file_refs": [
        "bot/strategy_engine.py:7183-7204 (existing-position loop)",
        "bot/strategy_engine.py:7057 (run_position_heartbeat_cycle)",
        "run_trader_loop.py:1172,1197 (lifecycle hook called after both cycle types)",
    ],
}

FULL_BOT_ORCHESTRATOR_NOTE = {
    "finding": "full_bot_orchestrator_is_not_the_live_orchestrator",
    "severity": "info",
    "description": (
        "bot/full_bot_orchestrator.py is a preview/dry-run report generator "
        "(ORCHESTRATOR_POLICY['preview_only']=True) that reads reports/d6/*.json and "
        "state/*.json and emits candidate actions; nothing in run_trader_loop.py or "
        "strategy_engine.py imports or calls it. The real live orchestrator is "
        "StrategyEngine.run_cycle() (bot/strategy_engine.py:7156), driven by "
        "run_trader_loop.py."
    ),
    "file_refs": ["bot/full_bot_orchestrator.py:27", "bot/strategy_engine.py:7156"],
}


# ---------------------------------------------------------------------------
# 2. Prompt inventory (ast-parsed from bot/prompts.py, no import/execution)
# ---------------------------------------------------------------------------

def _extract_prompts(prompts_file: Path) -> List[Dict[str, Any]]:
    if not prompts_file.is_file():
        return []
    source = prompts_file.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source)
    prompts: List[Dict[str, Any]] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.endswith("PROMPT"):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        text = node.value.value
        prompts.append(
            {
                "name": target.id,
                "line": node.lineno,
                "length_chars": len(text),
                "has_interpolation_placeholders": ("{" in text and "}" in text),
            }
        )
    return prompts


EXTRA_PROMPT_LOCATIONS = [
    {
        "name": "EXECUTION_PLANNER_PROMPT",
        "file": "bot/execution_planner.py",
        "line": 43,
        "consumer": "ReadOnlyExecutionPlanner.plan (bot/execution_planner.py:420)",
    },
    {
        "name": "build_analysis_json_prompt (inline)",
        "file": "bot/llm_clients_resilient.py",
        "line": 398,
        "consumer": "analyze_with_client / FallbackLLMRouter -- DEAD CODE, not imported by any runtime module",
    },
    {
        "name": "_judge_prompt (inline)",
        "file": "bot/full_bot_real_fresh_review_runner.py",
        "line": 80,
        "consumer": "offline 'real fresh review' evidence runner (not the live judge)",
    },
]


def _scan_for_secret_like_strings(text: str) -> List[str]:
    pattern = re.compile(r"(sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9_-]{20,}|(?i:bearer)\s+[A-Za-z0-9._-]{10,})")
    return pattern.findall(text)


def _scan_payload_modules_for_raw_api_key_usage(project_root: Path) -> Dict[str, List[str]]:
    """Confirm api_key only appears at client-construction lines, never in
    payload/dossier-building code (which would risk leaking credentials into
    a prompt)."""
    suspicious: Dict[str, List[str]] = {}
    for relative in ("bot/strategy_engine.py", "bot/execution_planner.py", "bot/trade_planner.py"):
        path = project_root / relative
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        hits = [
            f"{relative}:{i + 1}: {line.strip()}"
            for i, line in enumerate(lines)
            if "api_key" in line.lower() and "client(" not in line.lower()
        ]
        if hits:
            suspicious[relative] = hits
    return suspicious


# ---------------------------------------------------------------------------
# 3. Workflow efficiency questions (Section 4 of the audit request)
# ---------------------------------------------------------------------------

def _build_efficiency_section() -> Dict[str, Any]:
    enable_expensive_judge_gate = _bool_env("ENABLE_EXPENSIVE_JUDGE_GATE", True)
    enable_deepseek_preprocess = _bool_env("ENABLE_DEEPSEEK_PREPROCESS", False)
    enable_anthropic_fallback = _bool_env("ENABLE_ANTHROPIC_FALLBACK", False)
    max_candidates_for_deepseek_gate = _int_env("MAX_CANDIDATES_FOR_DEEPSEEK_GATE", 10)
    max_candidates_for_deep_analysis = _int_env("MAX_CANDIDATES_FOR_DEEP_ANALYSIS", 5)

    return {
        "final_judge_only_called_for_real_candidate": {
            "answer": True,
            "evidence": (
                "_should_call_expensive_judge (bot/strategy_engine.py:2790) gates the judge for "
                "new entries on constructive gate/synth/bull confidence thresholds; always called "
                "for existing open positions (so exits are never starved) or when "
                "ENABLE_EXPENSIVE_JUDGE_GATE=false."
            ),
            "current_flag_value_enable_expensive_judge_gate": enable_expensive_judge_gate,
        },
        "all_tickers_go_to_analyse_agent_or_only_top_candidates": {
            "answer": "only_top_candidates",
            "evidence": (
                f"Universe is ranked, top {max_candidates_for_deepseek_gate} (MAX_CANDIDATES_FOR_DEEPSEEK_GATE) "
                f"reach the entry gate; of those, only entry_gate decision in "
                f"{{analyze, priority_analyze}} are promoted to the full analyst stack, capped at "
                f"{max_candidates_for_deep_analysis} (MAX_CANDIDATES_FOR_DEEP_ANALYSIS)."
            ),
        },
        "reflection_on_every_wait_or_only_important_events": {
            "answer": "decision_outcomes_on_every_analyzed_ticker_trade_reflection_only_on_close",
            "evidence": (
                "_record_decision_outcome_snapshot runs for every analyzed ticker (cheap, "
                "deterministic, no LLM call) -- this is correct, it is not an extra LLM cost. "
                "_record_trade_reflection only fires on an actual position close."
            ),
        },
        "are_prompts_cached": {
            "answer": False,
            "evidence": "No lru_cache/memoize/cache_key/prompt_cache anywhere in the LLM call chain (grep returned zero hits). No Anthropic prompt-caching (cache_control) is used either.",
        },
        "no_trade_market_conditions_handled_cheaply": {
            "answer": True,
            "evidence": (
                "The cheap deterministic prefilter (_cheap_prefilter_candidate) and the nano "
                "entry gate filter out most no-trade conditions before any expensive model "
                "(mini/5.5) is invoked -- only entry_gate-promoted tickers reach the 6-analyst "
                "stack."
            ),
        },
        "open_positions_orders_guarded_without_expensive_entry_analysis": {
            "answer": True,
            "evidence": (
                "The hourly heartbeat path uses a deterministic prefilter "
                "(_position_heartbeat_prefilter) and only escalates to the nano position-watch "
                "LLM on a warning, and only escalates further to the full analyst+judge stack on "
                "true escalation. The lifecycle service hook (D2/D3) is fully deterministic, no "
                "LLM at all."
            ),
        },
        "dashboard_fully_read_only_no_own_llm_calls": {
            "answer": True,
            "evidence": (
                "dashboard/backend has zero openai/anthropic/deepseek/llm_clients imports; every "
                "service module docstring asserts 'no LLM/Coinbase calls'; the dashboard only "
                "shells out to tools/show_*.py / tools/build_*.py and reads reports/state files."
            ),
        },
        "deepseek_gate_enabled": enable_deepseek_preprocess,
        "anthropic_fallback_enabled": enable_anthropic_fallback,
    }


# ---------------------------------------------------------------------------
# 4. Model routing / DeepSeek runtime status / score-semantics (live env read)
# ---------------------------------------------------------------------------

def _build_model_routing_section() -> Dict[str, Any]:
    openai_model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
    openai_analyst_model = os.getenv("OPENAI_ANALYST_MODEL", openai_model)
    openai_judge_model = os.getenv("OPENAI_JUDGE_MODEL", "gpt-5.5")
    openai_trade_planner_model = os.getenv("OPENAI_TRADE_PLANNER_MODEL", openai_judge_model)
    openai_execution_planner_model = os.getenv("OPENAI_EXECUTION_PLANNER_MODEL", openai_judge_model)
    enable_deepseek_preprocess = _bool_env("ENABLE_DEEPSEEK_PREPROCESS", False)
    deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    enable_anthropic_fallback = _bool_env("ENABLE_ANTHROPIC_FALLBACK", False)
    anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-6")

    per_agent_model: Dict[str, Any] = {
        "entry_gate": {
            "provider": "openai", "model": "gpt-5.4-nano", "configurable_via_env": False,
            "note": "hardcoded OPENAI_NANO_MODEL constant, bot/strategy_engine.py:85,303",
        },
        "position_watch": {
            "provider": "openai", "model": "gpt-5.4-nano", "configurable_via_env": False,
            "note": "hardcoded OPENAI_NANO_MODEL constant, bot/strategy_engine.py:85,304",
        },
        "deepseek_preprocess": {
            "provider": "deepseek", "model": deepseek_model, "configurable_via_env": True,
            "env_var": "DEEPSEEK_MODEL", "active": enable_deepseek_preprocess,
        },
        "analyst_modules_regime_trend_breakout_meanrev_bull_bear_synth": {
            "provider": "openai", "model": openai_analyst_model, "configurable_via_env": True,
            "env_var": "OPENAI_ANALYST_MODEL (falls back to OPENAI_MODEL)",
        },
        "trade_planner": {
            "provider": "openai", "model": openai_trade_planner_model, "configurable_via_env": True,
            "env_var": "OPENAI_TRADE_PLANNER_MODEL (falls back to OPENAI_JUDGE_MODEL)",
        },
        "final_judge": {
            "provider": "openai (primary), anthropic (fallback)", "model": openai_judge_model,
            "anthropic_fallback_model": anthropic_model, "anthropic_fallback_active": bool(enable_anthropic_fallback),
            "configurable_via_env": True, "env_var": "OPENAI_JUDGE_MODEL",
        },
        "execution_planner": {
            "provider": "openai", "model": openai_execution_planner_model, "configurable_via_env": True,
            "env_var": "OPENAI_EXECUTION_PLANNER_MODEL (falls back to OPENAI_JUDGE_MODEL)",
        },
    }

    openai_only = (not enable_deepseek_preprocess) and (not enable_anthropic_fallback)

    return {
        "per_agent_model": per_agent_model,
        "deepseek_runtime_status": {
            "status": "runtime_active" if enable_deepseek_preprocess else "runtime_capable_but_disabled",
            "enable_deepseek_preprocess_env": enable_deepseek_preprocess,
            "evidence": (
                "bot/strategy_engine.py:296 only constructs DeepSeekClient when enable_deepseek_preprocess is "
                "True; bot/config.py:666-672 requires DEEPSEEK_API_KEY/DEEPSEEK_BASE_URL/DEEPSEEK_MODEL when "
                "enabled. The deepseek_pack/deepseek_gate/deepseek_hold_ok field and status names are stable "
                "log/state schema labels (logs/analysis.jsonl, bot/state_store.py position fields) kept for "
                "backward compatibility regardless of whether the client is active -- they are labels, not "
                "evidence of an active DeepSeek call, when this flag is False."
            ),
        },
        "anthropic_fallback_runtime_status": {
            "status": "runtime_active" if enable_anthropic_fallback else "runtime_capable_but_disabled",
            "enable_anthropic_fallback_env": enable_anthropic_fallback,
        },
        "openai_only_consistency": {
            "is_openai_only": openai_only,
            "evidence": (
                "True only when ENABLE_DEEPSEEK_PREPROCESS=false and ENABLE_ANTHROPIC_FALLBACK=false. "
                "entry_gate/position_watch are always OpenAI (hardcoded nano) regardless of these flags, so "
                "they never break OpenAI-only consistency."
            ),
        },
        "judge_model_source": {
            "fully_env_config_driven": True,
            "evidence": (
                "self.judge_model = getattr(self.cfg, 'openai_judge_model', DEFAULT_JUDGE_MODEL) "
                "(bot/strategy_engine.py:307); self.cfg.openai_judge_model = "
                "_get_optional_env('OPENAI_JUDGE_MODEL', 'gpt-5.5') (bot/config.py:214). No call site overrides "
                "self.judge_model with a hardcoded model string; 'gpt-5.5' only appears as the fallback default "
                "used when OPENAI_JUDGE_MODEL is unset in the environment."
            ),
        },
    }


def _build_score_semantics_section() -> Dict[str, Any]:
    enable_expensive_judge_gate = _bool_env("ENABLE_EXPENSIVE_JUDGE_GATE", True)
    judge_min_gate_confidence = _int_env("JUDGE_MIN_GATE_CONFIDENCE", 62)
    judge_min_synth_confidence = _int_env("JUDGE_MIN_SYNTH_CONFIDENCE", 60)
    judge_min_bull_score = _int_env("JUDGE_MIN_BULL_SCORE", 56)
    judge_max_bear_score = _int_env("JUDGE_MAX_BEAR_SCORE", 72)

    return {
        "directionality": {
            "bull_score": "higher_is_more_bullish",
            "bear_score": "higher_is_more_bearish_riskier",
            "evidence": (
                "bot/strategy_engine.py:2924-2925 (bear_score_dominant_warning fires when bear_score >= "
                "bull_score), bot/strategy_engine.py:3455-3485 (tactical-probe promotion requires bear_score "
                "capped well below bull_score), bot/trade_planner.py:325-328 (same direction, soft warnings)."
            ),
        },
        "current_thresholds": {
            "ENABLE_EXPENSIVE_JUDGE_GATE": enable_expensive_judge_gate,
            "JUDGE_MIN_GATE_CONFIDENCE": judge_min_gate_confidence,
            "JUDGE_MIN_SYNTH_CONFIDENCE": judge_min_synth_confidence,
            "JUDGE_MIN_BULL_SCORE": judge_min_bull_score,
            "JUDGE_MAX_BEAR_SCORE": judge_max_bear_score,
        },
        "pre_judge_cost_gate": {
            "purpose": "decides whether the expensive judge is called at all (cost control)",
            "location": "_should_call_expensive_judge, bot/strategy_engine.py:2791",
            "hard_or_soft": (
                "soft -- contributes to an escalation_score; does not hard-block on its own except for "
                "unrelated structural blockers (missing invalidation, market not tradeable, cooldown, etc.)"
            ),
        },
        "post_judge_deterministic_gate": {
            "purpose": (
                "fail-closed re-check that the judge's own approve_trade/BUY output still satisfies "
                "JUDGE_MIN_BULL_SCORE / JUDGE_MAX_BEAR_SCORE / JUDGE_MIN_SYNTH_CONFIDENCE"
            ),
            "location": (
                "_enforce_bull_bear_confidence_gate, bot/strategy_engine.py (called from "
                "_run_full_analysis_stack immediately after the valid_trade_plan checks, before "
                "_maybe_promote_wait_to_small_probe)"
            ),
            "hard_or_soft": "hard -- forces decision=wait, side=NONE, size_quote=0.0 on violation",
            "status": (
                "added in this audit pass -- previously these thresholds only gated judge invocation "
                "(_should_call_expensive_judge), never the judge's actual decision, so a judge call reached "
                "via the always-escalate paths (existing open position, gate disabled) could approve a trade "
                "the thresholds were meant to block."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_audit(*, root: Path = PROJECT_ROOT, generated_at: Optional[str] = None) -> Dict[str, Any]:
    prompts_file = root / "bot" / "prompts.py"
    prompts = _extract_prompts(prompts_file)
    prompts_source = prompts_file.read_text(encoding="utf-8", errors="replace") if prompts_file.is_file() else ""
    secret_like_in_prompts = _scan_for_secret_like_strings(prompts_source)
    suspicious_api_key_usage = _scan_payload_modules_for_raw_api_key_usage(root)

    total_prompt_chars = sum(p["length_chars"] for p in prompts)
    llm_layers = [layer for layer in LAYERS if layer.get("is_llm")]

    return {
        "phase": "multi_agent_prompt_audit_v1",
        "generated_at": generated_at or _now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "service_restart_attempted": False,
        "env_write_performed": False,
        "live_orchestrator": "bot.strategy_engine.StrategyEngine.run_cycle (bot/strategy_engine.py:7156), driven by run_trader_loop.py",
        "layers": LAYERS,
        "llm_layer_count": len(llm_layers),
        "deterministic_layer_count": len(LAYERS) - len(llm_layers),
        "findings": [
            DUPLICATE_CONTEXT_FINDING,
            RETRY_REBILLING_FINDING,
            NO_DUPLICATE_TICKER_PASS_FINDING,
            OPEN_POSITION_WATCH_FINDING,
            FULL_BOT_ORCHESTRATOR_NOTE,
        ],
        "prompt_inventory": {
            "prompts_py_file": str(prompts_file.relative_to(root)) if prompts_file.is_file() else None,
            "prompts": prompts,
            "total_prompt_chars_in_prompts_py": total_prompt_chars,
            "extra_prompt_locations_outside_prompts_py": EXTRA_PROMPT_LOCATIONS,
            "secret_like_strings_found_in_prompts_py": secret_like_in_prompts,
            "suspicious_api_key_usage_in_payload_modules": suspicious_api_key_usage,
            "secrets_in_prompts_conclusion": (
                "clean_no_secrets_found" if not secret_like_in_prompts and not suspicious_api_key_usage
                else "REVIEW_NEEDED_see_suspicious_api_key_usage_and_secret_like_strings_fields"
            ),
            "duplication_note": DUPLICATE_CONTEXT_FINDING["description"],
        },
        "workflow_efficiency": _build_efficiency_section(),
        "model_routing": _build_model_routing_section(),
        "score_semantics": _build_score_semantics_section(),
        "logging_destinations": {
            "decision_outcomes": "state/decision_outcomes.json (DecisionOutcomeStore, bot/decision_outcome_tracker.py)",
            "trade_reflections": "state/trade_reflections.jsonl (bot/trade_reflection.py)",
            "execution_outcomes": "logs/execution_outcomes.jsonl (bot/execution_outcome_tracker.py)",
            "llm_raw": "logs/llm_raw.jsonl",
            "llm_corrupt": "logs/llm_corrupt.jsonl",
            "llm_schema_drift": "logs/llm_schema_drift.jsonl",
            "llm_provider_errors": "logs/llm_provider_errors.jsonl",
            "llm_cost_ledger": "logs/llm_cost_ledger.jsonl (new in this audit -- see bot/llm_cost_ledger.py)",
            "phase_c_live_submit": "logs/phase_c_live_submit.jsonl",
            "phase_c43_lifecycle_service": "logs/phase_c43_lifecycle_service.jsonl",
        },
        "conclusion": {
            "multi_agent_system_correctness": "working_as_designed",
            "active_llm_agents": [layer["name"] for layer in llm_layers],
            "primary_cost_driver": DUPLICATE_CONTEXT_FINDING["finding"],
            "secondary_cost_driver": RETRY_REBILLING_FINDING["finding"],
        },
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Multi-Agent Pipeline + Prompt Audit",
        "",
        f"Generated: `{report.get('generated_at')}`",
        f"Live orchestrator: `{report.get('live_orchestrator')}`",
        "",
        f"LLM layers: {report.get('llm_layer_count')} | Deterministic layers: {report.get('deterministic_layer_count')}",
        "",
        "## Layers",
    ]
    for layer in report.get("layers", []):
        lines.append(f"### {layer['label']} (`{layer['name']}`)")
        lines.append(f"- is_llm: {layer.get('is_llm')}" + (f" (provider: {layer.get('provider')}, model: {layer.get('model_config_var')})" if layer.get("is_llm") else ""))
        lines.append(f"- invoked_from: {layer.get('invoked_from')}")
        lines.append(f"- input_shape: {layer.get('input_shape')}")
        lines.append(f"- prompt: {layer.get('prompt')}")
        lines.append(f"- output_shape: {layer.get('output_shape')}")
        lines.append(f"- forwarded_to: {layer.get('forwarded_to')}")
        lines.append(f"- logged_to: {layer.get('logged_to')}")
        lines.append(f"- skip_conditions: {layer.get('skip_conditions')}")
        lines.append("")

    lines.append("## Findings")
    for finding in report.get("findings", []):
        lines.append(f"### {finding['finding']} ({finding['severity']})")
        lines.append(finding["description"])
        for ref in finding.get("file_refs", []):
            lines.append(f"- `{ref}`")
        lines.append("")

    lines.append("## Prompt inventory")
    inv = report.get("prompt_inventory", {})
    for p in inv.get("prompts", []):
        lines.append(f"- `{p['name']}` ({p['length_chars']} chars, line {p['line']})")
    lines.append(f"- total_prompt_chars_in_prompts_py: {inv.get('total_prompt_chars_in_prompts_py')}")
    lines.append(f"- secrets_in_prompts_conclusion: **{inv.get('secrets_in_prompts_conclusion')}**")
    lines.append("")

    lines.append("## Workflow efficiency")
    for key, value in report.get("workflow_efficiency", {}).items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")

    lines.append("## Model routing")
    routing = report.get("model_routing", {})
    lines.append("### Per-agent model")
    for agent, info in routing.get("per_agent_model", {}).items():
        lines.append(f"- `{agent}`: {info}")
    for key in ("deepseek_runtime_status", "anthropic_fallback_runtime_status", "openai_only_consistency", "judge_model_source"):
        lines.append(f"- `{key}`: {routing.get(key)}")
    lines.append("")

    lines.append("## Score semantics")
    semantics = report.get("score_semantics", {})
    for key, value in semantics.items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")

    lines.append("## Conclusion")
    conclusion = report.get("conclusion", {})
    for key, value in conclusion.items():
        lines.append(f"- `{key}`: {value}")

    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only multi-agent pipeline + prompt audit.")
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--json-out")
    parser.add_argument("--md-out")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_audit(root=Path(args.root))

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.md_out:
        out_path = Path(args.md_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_markdown(report), encoding="utf-8")
    if args.json or not (args.json_out or args.md_out):
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
