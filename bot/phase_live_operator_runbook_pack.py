from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, List

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE_LIVE_OPERATOR_RUNBOOK_PACK = "live_operator_runbook_pack_v1"
DEFAULT_PROVEN_PRODUCT = "BTC-USDC"
DEFAULT_MAX_NOTIONAL_USDC = Decimal("10")
BTC_USDC_TINY_ACTUAL_SUBMIT_ACK = "I_APPROVE_BTC_USDC_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC"
BTC_USDC_TINY_DIRECT_START_COMMAND = (
    "BTC_USDC_TINY_ACTUAL_SUBMIT_ACK=I_APPROVE_BTC_USDC_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC "
    "tools/operator_btc_usdc_tiny_env.sh .venv/bin/python run_trader_loop.py"
)


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def _command(text: str, purpose: str, expected: str, blocks_if: str) -> Dict[str, str]:
    return {
        "command": text,
        "purpose": purpose,
        "expected": expected,
        "blocks_if": blocks_if,
    }


def _route(
    name: str,
    *,
    value: int,
    risk: int,
    testability: int,
    implementation_size: int,
    loop_reduction: int,
    operator_usefulness: int,
    state_impact: str,
    ack_required: str,
    verdict: str,
) -> Dict[str, Any]:
    return {
        "name": name,
        "score_scale": "1_low_to_5_high_except_risk_and_implementation_size",
        "value": value,
        "risk": risk,
        "testability": testability,
        "implementation_size": implementation_size,
        "loop_reduction": loop_reduction,
        "operator_usefulness": operator_usefulness,
        "state_impact": state_impact,
        "ack_required": ack_required,
        "verdict": verdict,
    }


def build_route_scores() -> List[Dict[str, Any]]:
    return [
        _route(
            "Route A - Docs-only operator runbook",
            value=2,
            risk=1,
            testability=2,
            implementation_size=1,
            loop_reduction=2,
            operator_usefulness=3,
            state_impact="docs_only",
            ack_required="none_for_docs",
            verdict="valid_but_too_manual",
        ),
        _route(
            "Route B - Preflight + monitoring command pack",
            value=4,
            risk=1,
            testability=4,
            implementation_size=2,
            loop_reduction=4,
            operator_usefulness=4,
            state_impact="reports_only",
            ack_required="none_until_operator_live_start",
            verdict="good_before_and_during_run_but_missing_post_run_collection",
        ),
        _route(
            "Route C - Post-run evidence collection tool",
            value=3,
            risk=1,
            testability=4,
            implementation_size=2,
            loop_reduction=3,
            operator_usefulness=3,
            state_impact="reports_only",
            ack_required="none_for_local_logs_state_hashes",
            verdict="useful_after_run_but_does_not_reduce_start_risk",
        ),
        _route(
            "Route D - Combined operator-start pack",
            value=5,
            risk=1,
            testability=5,
            implementation_size=3,
            loop_reduction=5,
            operator_usefulness=5,
            state_impact="docs_and_reports_only",
            ack_required="none_for_pack_build_live_start_still_requires_operator",
            verdict="chosen",
        ),
        _route(
            "Route E - Config/start-script mutation alternative",
            value=3,
            risk=4,
            testability=3,
            implementation_size=4,
            loop_reduction=4,
            operator_usefulness=4,
            state_impact="would_touch_runtime_behavior",
            ack_required="separate_config_or_service_ack_required",
            verdict="rejected_for_this_task",
        ),
    ]


def build_preflight_commands() -> List[Dict[str, str]]:
    return [
        _command(
            ".venv/bin/python tools/build_live_operator_runbook_pack.py --json-out reports/d6/operator-24h-live-test-pack-$(date -u +%Y%m%d).json --markdown-out reports/d6/operator-24h-live-test-pack-$(date -u +%Y%m%d).md",
            "Build a fresh local report-only operator pack before start review.",
            "status=operator_started_24h_live_test_pack_ready and safety flags remain false/blocked where required.",
            "the report records live action, Coinbase call, state write, learning-to-execution, parameter change, or all-ticker scope.",
        ),
        _command(
            "tools/operator_btc_usdc_tiny_env.sh .venv/bin/python tools/show_btc_usdc_tiny_live_preflight.py --json-out reports/d6/btc-usdc-tiny-live-preflight-$(date -u +%Y%m%d).json --markdown-out reports/d6/btc-usdc-tiny-live-preflight-$(date -u +%Y%m%d).md",
            "Evaluate the effective operator override config for BTC-USDC-only tiny-budget scope without editing .env.",
            "status=pass_btc_usdc_tiny_preflight, allowed_tickers=[BTC-USDC], phase_c_allowed_tickers=[BTC-USDC], all order/notional caps <=10 USDC, max new/open orders = 1, live exits disabled, actual submit disabled pre-ACK.",
            "status is blocked, any non-BTC ticker appears, any cap exceeds 10 USDC, max new/open order limit is not 1, live exits are enabled, learning-to-execution is enabled, or actual submit is enabled without exact ACK.",
        ),
        _command(
            "tools/operator_btc_usdc_tiny_env.sh .venv/bin/python run_trader_loop.py --startup-diagnostic",
            "Verify run_trader_loop.py sees the same BTC-USDC-only runtime ticker scope without constructing StrategyEngine or starting a cycle.",
            "effective_runtime_tickers=[BTC-USDC], phase_c_allowed_tickers=[BTC-USDC], tiny_mode_active=true, fail_closed=false, no_llm_call=true, no_coinbase_call=true, state_write_performed=false.",
            "fail_closed=true, any non-BTC ticker appears, tiny_mode_active is false under the wrapper, or the command exits non-zero.",
        ),
        _command(
            "python3 tools/show_open_orders.py --open-only --json --limit 20",
            "Confirm local orderstore has no open orders.",
            "summary.open_orders=0 and orders=[]",
            "any open order exists or the tool errors.",
        ),
        _command(
            "python3 tools/show_function_preservation_audit.py --fail-on-review",
            "Confirm live-submit and D.3 safety flags are still observe-only where required.",
            "Status: ok_observe_only",
            "audit status is not ok_observe_only, or submit/exit flags drift unexpectedly.",
        ),
        _command(
            "python3 tools/show_phase_d3_controlled_live_exits.py --ticker BTC-USDC --json",
            "Confirm there is no manageable BTC-USDC D.3 exit lifecycle.",
            "status=d3_no_manageable_open_position and open_d3_exit_orders.total_open_d3_exit_orders=0",
            "an active D.3 exit, manageable position, duplicate, or oversell warning appears.",
        ),
        _command(
            "sha256sum state/open_orders.json state/positions.json",
            "Capture before-run local state hashes.",
            "hashes are recorded in the operator notes and later compared after stop.",
            "hashes drift before start without a known local action.",
        ),
        _command(
            "python3 - <<'PY'\nfrom bot.config import BotConfig\nc=BotConfig(); c.validate(); print(c.to_dict())\nPY",
            "Print effective runtime config for operator review without editing .env.",
            "Operator verifies ALLOWED_TICKERS/PHASE_C_ALLOWED_TICKERS are BTC-USDC-only, max notional is tiny, learning-to-execution is absent, and actual submit flags match the separately ACKed scope.",
            "effective config includes non-BTC live scope, excessive notional, live exits, parameter mutation, or any unapproved submit path.",
        ),
    ]


def build_operator_sequence() -> List[Dict[str, str]]:
    return [
        {
            "step": "A",
            "title": "Confirm service/process scope",
            "summary": "Confirm Codex is not starting the live process and any operator-maintained wrapper preserves BTC-USDC-only tiny scope.",
        },
        {
            "step": "B",
            "title": "Fresh BTC-USDC tiny preflight",
            "summary": "Run the tiny preflight under tools/operator_btc_usdc_tiny_env.sh with .venv/bin/python.",
        },
        {
            "step": "C",
            "title": "Startup diagnostic",
            "summary": "Run run_trader_loop.py --startup-diagnostic under the same wrapper before any live start.",
        },
        {
            "step": "D",
            "title": "Baseline state hashes",
            "summary": "Capture sha256sum for state/open_orders.json and state/positions.json immediately before start.",
        },
        {
            "step": "E",
            "title": "Exact operator ACK live-start command",
            "summary": "Operator start only, using .venv/bin/python and the exact BTC-USDC tiny actual-submit ACK.",
        },
        {
            "step": "F",
            "title": "During-run monitor command",
            "summary": "Use tools/show_btc_usdc_24h_live_monitor.py with --since-utc and baseline hashes.",
        },
        {
            "step": "G",
            "title": "Stop rules",
            "summary": "OK continues, WATCH requires review, STOP_NOW stops the operator run and forbids apply/repair/exit without ACK.",
        },
        {
            "step": "H",
            "title": "Post-run evidence pack",
            "summary": "Build the windowed post-run evidence pack with explicit start/stop UTC.",
        },
        {
            "step": "I",
            "title": "C4/D1 branch map selection",
            "summary": "Build the C4/D1 branch map and select Branch A-G before any fill-to-position or D2/D3 action.",
        },
        {
            "step": "J",
            "title": "No-apply/no-repair/no-exit boundaries",
            "summary": "Fill apply, lifecycle apply, repair, live D3 exit, cancel/replace/reprice and Coinbase poll remain separate ACK boundaries.",
        },
    ]


def build_monitoring_commands() -> List[Dict[str, str]]:
    return [
        _command(
            "python3 tools/show_btc_usdc_24h_live_monitor.py --json --since-utc <OPERATOR_START_UTC> --baseline-open-orders-hash <PRE_START_OPEN_ORDERS_SHA256> --baseline-positions-hash <PRE_START_POSITIONS_SHA256>",
            "Preferred local read-only during-run monitor from logs/state/process evidence only.",
            "classification is OK or a reviewed WATCH; scope remains BTC-USDC-only and state hashes match expected run evidence.",
            "classification=STOP_NOW, non-BTC ticker evidence, second open order, unexpected SELL/exit, retry storm, lifecycle apply signal, replication enabled, or state drift appears.",
        ),
        _command(
            "tail -n 120 logs/loop.log",
            "Inspect recent loop decisions and errors.",
            "no Traceback, no duplicate/oversell warning, no unexpected SELL, no all-ticker execution.",
            "Traceback, retry storm, unauthorized symbol/action, or dangerous decision appears.",
        ),
        _command(
            "tail -n 80 logs/cycle_summary.jsonl",
            "Inspect cycle-level decisions and executed counts.",
            "executed count stays within the approved small BTC-USDC scope.",
            "executed count or ticker scope exceeds the ACKed run definition.",
        ),
        _command(
            "tail -n 80 logs/heartbeat_summary.jsonl",
            "Inspect hourly position heartbeat behavior.",
            "no unapproved close/reduce execution and no repeated errors.",
            "unexpected close/reduce, repeated full-review errors, or runtime instability appears.",
        ),
        _command(
            "python3 tools/show_open_orders.py --open-only --json --limit 20",
            "Local open-order snapshot during the run.",
            "open orders remain within the exact ACKed BTC-USDC small-budget scope.",
            "non-BTC order, second open order, duplicate, stale order, or unknown open order appears.",
        ),
        _command(
            "python3 tools/show_function_preservation_audit.py --fail-on-review",
            "Repeat local safety audit during monitoring.",
            "ok_observe_only or the exact pre-approved live flags only.",
            "unapproved submit/exit/learning/config flag drift appears.",
        ),
    ]


def build_post_run_commands() -> List[Dict[str, str]]:
    return [
        _command(
            "python3 tools/build_btc_usdc_24h_post_run_evidence_pack.py --start-utc <OPERATOR_START_UTC> --stop-utc <OPERATOR_STOP_UTC> --baseline-open-orders-hash <PRE_START_OPEN_ORDERS_SHA256> --baseline-positions-hash <PRE_START_POSITIONS_SHA256> --json-out reports/live/btc-usdc-24h-evidence-$(date -u +%Y%m%d).json --markdown-out reports/live/btc-usdc-24h-evidence-$(date -u +%Y%m%d).md",
            "Build the local/read-only post-run evidence pack for the exact operator-run UTC window.",
            "JSON/Markdown reports are written under reports/live/ and old historical logs are excluded by start/stop UTC.",
            "classification=STOP_NOW or evidence is insufficient to explain state/order changes.",
        ),
        _command(
            "python3 tools/build_c4_d1_handoff_branch_map.py --json-out reports/d6/c4-d1-handoff-branch-map-$(date -u +%Y%m%d).json --markdown-out reports/d6/c4-d1-handoff-branch-map-$(date -u +%Y%m%d).md",
            "Build the read-only C4/D1 branch map after post-run evidence collection.",
            "Branch A-G is selected from local state and the operator can distinguish evidence review, preview, local apply, D2 plan, D3 preview and live D3 exit submit.",
            "Branch G STOP_NOW or any branch requires an ACK boundary before apply/repair/cancel/reprice/live exit.",
        ),
        _command(
            "sha256sum state/open_orders.json state/positions.json",
            "Capture after-run state hashes.",
            "hashes are saved with stop time and compared to before-run hashes.",
            "state changed without known order/lifecycle evidence.",
        ),
        _command(
            "python3 tools/show_open_orders.py --open-only --json --limit 50",
            "Capture final local open-order state.",
            "no unexpected open orders remain.",
            "unknown, duplicate, non-BTC, or stale open order remains.",
        ),
        _command(
            "python3 tools/show_function_preservation_audit.py --fail-on-review",
            "Capture final function preservation state.",
            "audit passes or only exact acknowledged live flags are present.",
            "unapproved function/safety drift appears.",
        ),
        _command(
            "python3 tools/show_execution_outcomes.py --json 2>/dev/null || python3 tools/show_execution_outcomes.py",
            "Collect local execution outcome evidence when available.",
            "summary is captured for Codex troubleshooting.",
            "tool reports corruption or impossible lifecycle/order evidence.",
        ),
        _command(
            "python3 tools/show_phase_d5_execution_metrics.py --json 2>/dev/null || python3 tools/show_phase_d5_execution_metrics.py",
            "Collect D.5 execution metrics if logs contain relevant events.",
            "report-only metrics are captured; no learning-to-execution bridge is enabled.",
            "metrics imply parameter mutation, ranking approval, or missing fill evidence.",
        ),
    ]


def build_operator_started_24h_live_test_pack(
    *,
    generated_at: str | None = None,
    proven_product: str = DEFAULT_PROVEN_PRODUCT,
    max_notional_usdc: Decimal | str = DEFAULT_MAX_NOTIONAL_USDC,
    start_surface: str = "operator_external_start_bash_or_direct_python_run_trader_loop",
    initial_safety: Dict[str, Any] | None = None,
    state_hashes: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    max_notional = Decimal(str(max_notional_usdc))
    hard_blockers = [
        "no_fresh_local_preflight_pass",
        "no_separate_operator_live_start_ack_in_this_task",
        "coinbase_read_only_preflight_ack_missing_for_any_exchange_snapshot",
        "submit_ack_missing_for_any_live_order",
        "all_ticker_live_scope_not_proven",
        "learning_to_execution_forbidden",
        "parameter_mutation_forbidden",
    ]
    return {
        "generated_at": generated_at or now_iso(),
        "phase": PHASE_LIVE_OPERATOR_RUNBOOK_PACK,
        "status": "operator_started_24h_live_test_pack_ready",
        "task_name": "Prepare Operator-Started 24h Live Test Workflow v1",
        "chosen_route": "Route D - Combined operator-start pack",
        "chosen_route_rationale": "Highest operator usefulness and loop reduction while remaining docs/reports-only and testable.",
        "route_scores": build_route_scores(),
        "operator_sequence": build_operator_sequence(),
        "scope": {
            "proven_product": proven_product,
            "recommended_live_scope": [proven_product],
            "all_ticker_live_trading": "blocked_until_separate_coverage_and_ack",
            "max_notional_usdc_placeholder": str(max_notional),
            "budget_policy": "tiny_budget_only_exact_value_must_be_reconfirmed_by_operator_before_start",
            "live_window": "24h_operator_started_and_operator_stopped",
            "start_surface": start_surface,
            "codex_starts_live_run": False,
            "operator_starts_live_run": True,
        },
        "hard_boundaries": {
            "no_start_by_codex": True,
            "no_service_restart_by_codex": True,
            "no_coinbase_call_in_pack_build": True,
            "no_live_action_in_pack_build": True,
            "no_state_write_in_pack_build": True,
            "no_env_mutation": True,
            "no_strategy_risk_prompt_parameter_mutation": True,
            "no_all_ticker_live_enablement": True,
            "no_learning_to_execution": True,
            "no_openai_api_call": True,
            "no_sudo_or_package_install": True,
        },
        "before_run_preflight": {
            "commands": build_preflight_commands(),
            "must_pass": [
                "open_orders=0",
                "open_d3_exit=0",
                "function_audit=ok_observe_only_or_exact_ACKed_live_flags",
                "BTC-USDC only for live scope",
                "tiny max notional",
                "learning_to_execution disabled",
                "parameter mutation disabled",
                "state hashes captured",
                "btc_usdc_tiny_live_preflight=pass",
            ],
            "blocks_run": hard_blockers,
        },
        "start_instructions": {
            "working_directory": "/root/apps/Crypto/coinbase_bot",
            "venv_activation": "source .venv/bin/activate",
            "preferred_operator_start": "Use the operator-maintained start bash only after it is verified to set BTC-USDC-only tiny-budget live scope.",
            "repo_direct_start_if_no_bash_exists": BTC_USDC_TINY_DIRECT_START_COMMAND,
            "pre_ack_preflight_wrapper": "tools/operator_btc_usdc_tiny_env.sh .venv/bin/python tools/show_btc_usdc_tiny_live_preflight.py",
            "startup_diagnostic": "tools/operator_btc_usdc_tiny_env.sh .venv/bin/python run_trader_loop.py --startup-diagnostic",
            "actual_submit_ack": BTC_USDC_TINY_ACTUAL_SUBMIT_ACK,
            "do_not_change": [
                ".env without separate config ACK",
                "risk/strategy/prompt/parameter files",
                "all-ticker live flags",
                "learning-to-execution flags",
            ],
            "note": "This pack does not assert current .env is safe; operator must run preflight and inspect effective config immediately before start.",
        },
        "during_run_monitoring": {
            "cadence": "operator: first 15 minutes closely, then every 15 minutes or on alert; Codex does not monitor-loop",
            "commands": build_monitoring_commands(),
            "danger_conditions": [
                "non-BTC-USDC live order or decision appears",
                "notional exceeds exact ACKed cap",
                "second open order or duplicate/oversell warning appears",
                "unexpected SELL/exit without a managed BTC-USDC position",
                "Traceback or repeated provider/runtime errors",
                "state hashes drift without matching evidence",
                "learning/parameter mutation/ranking approval appears",
            ],
        },
        "stop_procedure": {
            "normal_stop": "Ctrl+C in the operator-started foreground shell, or the operator's existing stop command for their bash/service wrapper.",
            "avoid": "Do not kill abruptly unless the process ignores normal stop or a dangerous action is imminent.",
            "after_stop": [
                "capture final logs",
                "capture state hashes",
                "run local open-order and function audits",
                "preserve any Coinbase UI/export evidence gathered by the operator",
            ],
        },
        "post_run_evidence_collection": {
            "commands": build_post_run_commands(),
            "c4_d1_branch_map_note": "D2/D3 preview is not live exit permission; D3 preview must keep submit_live=False and live exits require separate future ACK.",
            "paste_back_to_codex": [
                "exact start and stop UTC timestamps",
                "preflight pack path and hashes",
                "before/after sha256sum lines",
                "last 120 lines of logs/loop.log",
                "last 80 lines of logs/cycle_summary.jsonl",
                "last 80 lines of logs/heartbeat_summary.jsonl",
                "any logs/loop_errors.jsonl entries during the window",
                "Coinbase UI/export order and fill evidence if operator gathered it under a separate ACK",
                "any manual stop reason",
            ],
        },
        "codex_troubleshooting_loop": {
            "operator_brings": "logs, state hashes, report pack, exact observed issue, and any exchange evidence",
            "codex_then_does": "offline reproduction, focused tests, report-only diagnostics, and patches only after reading logs",
            "codex_still_does_not_do": "no repair/apply/cancel/submit/restart/config mutation without separate exact ACK",
        },
        "initial_safety": initial_safety or {},
        "state_hashes": state_hashes or {},
        "warnings": [
            "BTC-USDC is the only end-to-end proven live workflow path",
            "other configured tickers remain configured-only for live workflow purposes",
            "stale denormalized reserved_base_open_exit_orders warning remains unrepaired",
            "TP_CLOSE fee field gap remains unrepaired",
            "bwrap missing warning remains maintenance-only",
            "this pack did not start a live run",
        ],
        "live_start_blockers": hard_blockers,
        "blockers": [],
        "required_future_acks": {
            "operator_start_24h_scope": "separate prompt with exact product, max notional, runtime config, start/stop window, and stop thresholds",
            "coinbase_read_only_preflight": "separate ACK before any Coinbase read-only account/order/product snapshot by Codex",
            "submit_live_order": "separate exact submit ACK before any live order",
            "fill_to_position_apply": "I_UNDERSTAND_AND_APPROVE_C45_FILL_TO_POSITION_APPLY",
            "cancel_replace_reprice": "separate exact order-id and action ACK",
            "lifecycle_apply": "separate exact evidence ACK",
            "local_repair": "separate exact repair ACK",
            "live_d3_exit_submit": "separate exact D3 live exit submit ACK",
            "config_or_parameter_mutation": "separate exact diff ACK",
        },
        **_safety_flags(),
    }


__all__ = [
    "DEFAULT_MAX_NOTIONAL_USDC",
    "DEFAULT_PROVEN_PRODUCT",
    "PHASE_LIVE_OPERATOR_RUNBOOK_PACK",
    "build_monitoring_commands",
    "build_operator_started_24h_live_test_pack",
    "build_operator_sequence",
    "build_post_run_commands",
    "build_preflight_commands",
    "build_route_scores",
]
