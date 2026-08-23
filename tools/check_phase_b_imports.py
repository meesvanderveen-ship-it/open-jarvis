#!/usr/bin/env python3
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig
from bot.execution_planner import ReadOnlyExecutionPlanner, ExecutionPlanner
from bot.limit_order_manager import PaperLimitOrderManager
from bot.order_store import OrderStore
from bot.order_plan import OrderPlan, PaperOrderPlan, build_order_intent_from_execution_plan, is_actionable_order_intent
from bot.pending_order_intents import PendingOrderIntentStore, build_pending_intent_from_execution_plan, build_watchlist_intent_from_analysis, build_pending_order_intent_context
from bot.phase_c_live_guard import evaluate_phase_c_live_entry_readiness, summarize_phase_c_readiness
from bot.phase_c_live_submitter import prepare_phase_c_live_entry_submission, build_phase_c_live_entry_payload, run_phase_c_live_submit_dry_run
from bot.phase_c_pilot_readiness import build_phase_c_pilot_readiness_report, assess_phase_c_pilot_config, summarize_phase_c_submit_audit
from bot.phase_c31_go_no_go import build_phase_c31_go_no_go_report, assess_phase_c31_pre_go_no_go, build_phase_c31_env_preview
from bot.phase_c32_staged_pilot_config import build_phase_c32_staged_pilot_report, assess_phase_c32_staged_preflight, build_phase_c32_staged_config
from bot.phase_c33_candidate_preflight import build_phase_c33_final_preflight_report
from bot.phase_c34_candidate_snapshot import build_phase_c34_candidate_snapshot_report, build_phase_c34_candidate_from_sources
from bot.phase_c35_candidate_watcher import build_phase_c35_candidate_watcher_report
from bot.phase_c36_final_pilot_dry_run import build_phase_c36_final_pilot_dry_run_report
from bot.phase_c37_candidate_promotion_hardening import build_phase_c37_candidate_promotion_hardening_report, assess_phase_c37_candidate_summary, summarize_phase_c37_live_risk_bridge
from bot.phase_c38_final_pilot_executor_scaffold import build_phase_c38_final_pilot_executor_report, C38_HUMAN_GO_ACK
from bot.phase_c40_live_order_safety_layer import build_phase_c40_live_order_safety_report, assess_c40_order_safety, collect_live_open_orders_snapshot
from bot.phase_c41_pre_live_readiness import build_phase_c41_pre_live_readiness_report, assess_phase_c41_pre_live_readiness, C41_EMERGENCY_CANCEL_ACK
from bot.phase_c42_final_pre_live_autonomy_bridge import build_phase_c42_final_pre_live_autonomy_bridge_report, assess_phase_c42_final_autonomy_bridge, C42_FINAL_ARM_ACK
from bot.phase_c43_autonomous_entry_live import build_phase_c43_status_report, build_phase_c43_guard_and_submit_preparation, reconcile_phase_c43_fills_to_positions
from bot.phase_c43_one_entry_smoke_test import run_c43_one_live_entry_smoke_test, C43_ONE_ENTRY_SMOKE_ACK
from bot.phase_d2_position_executor import build_phase_d2_position_executor_report, build_multi_exit_bracket_lite_plan, assess_minimum_net_edge, is_d2_manageable_open_position
from bot.phase_d3_controlled_live_exits import build_phase_d3_controlled_live_exit_report, assess_phase_d3_exit_readiness, submit_phase_d3_controlled_exit, D3_ACK
from bot.phase_d31_lifecycle_readiness import build_phase_d31_lifecycle_readiness_report, assess_phase_d31_entry_pilot_readiness, D31_ENTRY_ARM_ACK
from bot.phase_d32_llm_pre_live_health import build_phase_d32_llm_pre_live_health_report, D32_PHASE


def main() -> int:
    cfg = BotConfig()
    cfg.validate()
    print("CONFIG OK")
    print("enable_read_only_execution_planner =", cfg.enable_read_only_execution_planner)
    print("execution_planner_call_on_wait     =", cfg.execution_planner_call_on_wait)
    print("enable_limit_order_manager         =", cfg.enable_limit_order_manager)
    print("enable_live_limit_orders           =", cfg.enable_live_limit_orders)
    print("enable_live_entry_orders           =", cfg.enable_live_entry_orders)
    print("enable_live_exit_orders            =", cfg.enable_live_exit_orders)
    print("enable_phase_c_live_small_limit_orders =", getattr(cfg, "enable_phase_c_live_small_limit_orders", False))
    print("enable_deepseek_preprocess      =", getattr(cfg, "enable_deepseek_preprocess", False))
    print("enable_anthropic_fallback       =", getattr(cfg, "enable_anthropic_fallback", False))
    print("llm_corrupt_max_raw_chars       =", getattr(cfg, "llm_corrupt_max_raw_chars", None))
    print("llm_context_hygiene_enabled    =", getattr(cfg, "llm_context_hygiene_enabled", None))
    print("llm_payload_string_max_chars   =", getattr(cfg, "llm_payload_string_max_chars", None))
    print("enable_phase_d32_llm_pre_live_health =", getattr(cfg, "enable_phase_d32_llm_pre_live_health", None))
    print("phase_d32_llm_health_window_minutes =", getattr(cfg, "phase_d32_llm_health_window_minutes", None))
    print("phase_c_allowed_tickers            =", getattr(cfg, "phase_c_allowed_tickers", []))
    print("phase_c_max_order_quote            =", getattr(cfg, "phase_c_max_order_quote", None))
    print("enable_phase_c_live_submit_infrastructure =", getattr(cfg, "enable_phase_c_live_submit_infrastructure", True))
    print("enable_phase_c_actual_coinbase_submit =", getattr(cfg, "enable_phase_c_actual_coinbase_submit", False))
    print("phase_c_live_order_post_only     =", getattr(cfg, "phase_c_live_order_post_only", True))
    print("enable_autonomous_small_live_orderbook_mode =", getattr(cfg, "enable_autonomous_small_live_orderbook_mode", False))
    print("autonomous_max_order_quote       =", getattr(cfg, "autonomous_max_order_quote", None))
    print("autonomous_max_open_orders       =", getattr(cfg, "autonomous_max_open_orders", None))
    print("enable_phase_d3_controlled_live_exits =", getattr(cfg, "enable_phase_d3_controlled_live_exits", None))
    print("enable_phase_d3_actual_exit_submit =", getattr(cfg, "enable_phase_d3_actual_exit_submit", None))
    print("phase_d3_max_exit_order_quote   =", getattr(cfg, "phase_d3_max_exit_order_quote", None))
    print("enable_paper_reserved_balance_checks =", cfg.enable_paper_reserved_balance_checks)
    print("enable_paper_order_budget_enforcement =", cfg.enable_paper_order_budget_enforcement)
    print("enable_paper_pending_order_intents =", cfg.enable_paper_pending_order_intents)
    print("enable_paper_watchlist_intents_from_gate_watch =", cfg.enable_paper_watchlist_intents_from_gate_watch)
    print("paper_pending_intent_ttl_hours     =", cfg.paper_pending_intent_ttl_hours)
    print("paper_pending_intent_max_records   =", cfg.paper_pending_intent_max_records)
    print("paper_pending_intent_min_gate_confidence =", cfg.paper_pending_intent_min_gate_confidence)
    print("paper_pending_intent_mark_needs_fresh_analysis_status =", cfg.paper_pending_intent_mark_needs_fresh_analysis_status)
    print("paper_pending_intent_max_replaced_per_ticker =", cfg.paper_pending_intent_max_replaced_per_ticker)
    print("paper_pending_intent_final_retention_hours =", cfg.paper_pending_intent_final_retention_hours)
    print("paper_pending_intent_dedupe_tolerance_pct =", cfg.paper_pending_intent_dedupe_tolerance_pct)
    print("paper_pending_intent_enable_dedupe_refresh =", cfg.paper_pending_intent_enable_dedupe_refresh)
    print("ReadOnlyExecutionPlanner import    =", ReadOnlyExecutionPlanner.__name__)
    print("ExecutionPlanner alias import      =", ExecutionPlanner.__name__)
    print("OrderPlan import                   =", OrderPlan.__name__)
    print("PaperOrderPlan import              =", PaperOrderPlan.__name__)
    print("PaperLimitOrderManager import      =", PaperLimitOrderManager.__name__)
    print("OrderStore import                  =", OrderStore.__name__)
    print("PendingOrderIntentStore import     =", PendingOrderIntentStore.__name__)
    print("Phase C guard imports              =", evaluate_phase_c_live_entry_readiness.__name__, summarize_phase_c_readiness.__name__)
    print("Phase C submit scaffold imports    =", prepare_phase_c_live_entry_submission.__name__, build_phase_c_live_entry_payload.__name__)
    print("Phase C dry-run audit import       =", run_phase_c_live_submit_dry_run.__name__)
    print("Phase C pilot readiness imports   =", build_phase_c_pilot_readiness_report.__name__, assess_phase_c_pilot_config.__name__, summarize_phase_c_submit_audit.__name__)
    print("Phase C31 go/no-go imports         =", build_phase_c31_go_no_go_report.__name__, assess_phase_c31_pre_go_no_go.__name__, build_phase_c31_env_preview.__name__)
    print("Phase C32 staged pilot imports     =", build_phase_c32_staged_pilot_report.__name__, assess_phase_c32_staged_preflight.__name__, build_phase_c32_staged_config.__name__)
    print("Phase C33 candidate preflight import=", build_phase_c33_final_preflight_report.__name__)
    print("Phase C34 candidate snapshot imports=", build_phase_c34_candidate_snapshot_report.__name__, build_phase_c34_candidate_from_sources.__name__)
    print("Phase C35 candidate watcher import=", build_phase_c35_candidate_watcher_report.__name__)
    print("Phase C36 final pilot dry-run import=", build_phase_c36_final_pilot_dry_run_report.__name__)
    print("Phase C37 promotion hardening imports=", build_phase_c37_candidate_promotion_hardening_report.__name__, assess_phase_c37_candidate_summary.__name__, summarize_phase_c37_live_risk_bridge.__name__)
    print("Phase C38 final pilot executor imports=", build_phase_c38_final_pilot_executor_report.__name__, C38_HUMAN_GO_ACK)
    print("Phase C40 live order safety imports=", build_phase_c40_live_order_safety_report.__name__, assess_c40_order_safety.__name__, collect_live_open_orders_snapshot.__name__)
    print("Phase C41 pre-live readiness imports=", build_phase_c41_pre_live_readiness_report.__name__, assess_phase_c41_pre_live_readiness.__name__, C41_EMERGENCY_CANCEL_ACK)
    print("Phase C42 autonomy bridge imports=", build_phase_c42_final_pre_live_autonomy_bridge_report.__name__, assess_phase_c42_final_autonomy_bridge.__name__, C42_FINAL_ARM_ACK)
    print("Phase C43 autonomous entry imports=", build_phase_c43_status_report.__name__, build_phase_c43_guard_and_submit_preparation.__name__, reconcile_phase_c43_fills_to_positions.__name__)
    print("Phase C43 one-entry smoke import=", run_c43_one_live_entry_smoke_test.__name__, C43_ONE_ENTRY_SMOKE_ACK)
    print("Phase D2 position executor imports=", build_phase_d2_position_executor_report.__name__, build_multi_exit_bracket_lite_plan.__name__, assess_minimum_net_edge.__name__)
    print("Phase D2.1 pre-D3 hygiene imports=", is_d2_manageable_open_position.__name__)
    print("Phase D3 controlled live exits imports=", build_phase_d3_controlled_live_exit_report.__name__, assess_phase_d3_exit_readiness.__name__, submit_phase_d3_controlled_exit.__name__, D3_ACK)
    print("Phase D3.1 lifecycle readiness imports=", build_phase_d31_lifecycle_readiness_report.__name__, assess_phase_d31_entry_pilot_readiness.__name__, D31_ENTRY_ARM_ACK)
    print("Phase D3.2 LLM pre-live health imports=", build_phase_d32_llm_pre_live_health_report.__name__, D32_PHASE)
    print("function imports                   = OK")
    if (cfg.enable_live_limit_orders or cfg.enable_live_entry_orders or cfg.enable_live_exit_orders) and not getattr(cfg, "enable_phase_c_live_small_limit_orders", False):
        print("ERROR: live limit-order flags staan aan zonder expliciete Phase-C kill switch.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
