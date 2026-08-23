# Testfailures: volledige categorisatie

Gegenereerd uit de echte testrun (Python 3.13). Alle failures hieronder
bestonden ook voor de audit: **PRE-EXISTING = JA** voor elke regel.

| Groep | Aantal | Core bot | Installer | Auth | Startup | Live trading |
|---|---|---|---|---|---|---|
| G1 Live-gates staan dicht (veilige paper-standaard) | 28 | NEE | NEE | NEE | NEE | NEE |
| G2 order_store-invariant strenger dan testfixture | 11 | NEE | NEE | NEE | NEE | NEE |
| G3 Verwachte configuratie-foutmeldingen afwijkend | 12 | NEE | NEE | NEE | NEE | NEE |
| G4 Paper-budget/reserveringen handhaven strenger | 6 | NEE | NEE | NEE | NEE | NEE |
| G5 Prompttekst gewijzigd t.o.v. testverwachting | 3 | NEE | NEE | NEE | NEE | NEE |
| G6 Operator-bashscripts / hardcoded serverpad | 6 | NEE | NEE | NEE | NEE | NEE |
| G7 Entry/exit-beleidslabels gewijzigd | 14 | NEE | NEE | NEE | NEE | NEE |
| G8 Overig: gevolg van geblokkeerde voorgaande stap | 21 | NEE | NEE | NEE | NEE | NEE |
| G9 Onvolledige testdubbel (mist methode van echte klasse) | 1 | NEE | NEE | NEE | NEE | NEE |


## G1 — Live-gates staan dicht (veilige paper-standaard) (28)

| Test | Module | Root cause |
|---|---|---|
| `test_status_mode_a_ready_with_mode_b_disabled` | `test_autonomous_live_run_status.py` | AssertionError: assert 'not_ready_p0_runtime_bug' == 'ready_for_mo...mous_live_run' |
| `test_current_open_d3_baseline_ready_with_stop_exit_preview_only` | `test_full_autonomous_run_readiness.py` | AssertionError: assert 'not_ready_p0_runtime_bug' == 'ready_for_mo...mous_live_run' |
| `test_mode_b_readiness_requires_exact_ack` | `test_full_autonomous_run_readiness.py` | assert False is True |
| `test_mode_c_market_orders_exact_ack_replication_false_ready` | `test_full_autonomous_run_readiness.py` | assert False is True |
| `test_adapter_report_can_consume_promoted_candidate_in_dry_run_and_submit_remains_ack_gated` | `test_full_bot_near_miss_phase_c_review.py` | assert False is True |
| `test_full_pipeline_health_report_uses_existing_reports_and_stays_red` | `test_full_pipeline_health.py` | assert False is True |
| `test_full_poc_allows_default_quote_50_inside_live_rails` | `test_full_poc_workflow_readiness.py` | assert False is True |
| `test_full_poc_missing_mode_c_ack_does_not_block_orderbook_only_route` | `test_full_poc_workflow_readiness.py` | assert False is True |
| `test_full_poc_with_mode_b_mode_c_and_replication_false_is_ready` | `test_full_poc_workflow_readiness.py` | AssertionError: assert 'not_ready_p0_runtime_bug' == 'ready_for_fu...o_replication' |
| `test_full_workflow_entry_submitter_can_run_with_d3_exit_flags_enabled` | `test_full_workflow_live_max3x20.py` | assert False is True |
| `test_market_buy_quote_rails_and_preview_no_live_call` | `test_market_order_mode_c_governance.py` | assert False is True |
| `test_market_order_mode_c_requires_exact_ack_and_replication_off` | `test_market_order_mode_c_governance.py` | assert False is True |
| `test_phase_c21_simulate_ready_guard_still_blocks_actual_submit` | `test_phase_c21_live_submit_dry_run_audit.py` | assert False is True |
| `test_c2_payload_builder_creates_base_sized_limit_preview_without_submit` | `test_phase_c2_live_submit_scaffold.py` | assert False is True |
| `test_c2_submit_branch_requires_explicit_submit_argument_and_extra_flag` | `test_phase_c2_live_submit_scaffold.py` | assert False is True |
| `test_c31_ready_for_human_review_when_c30_runtime_and_guard_are_green_but_actual_submit_false` | `test_phase_c31_go_no_go.py` | assert False is True |
| `test_c32_full_report_ready_for_human_review_under_staged_config_with_candidate` | `test_phase_c32_staged_pilot_config.py` | assert False is True |
| `test_c34_report_can_extract_from_logs_and_reach_final_preflight_ready_with_real_risk` | `test_phase_c34_candidate_snapshot.py` | assert False is True |
| `test_c38_all_final_hardlocks_use_submitter_with_fake_client_only` | `test_phase_c38_final_pilot_executor_scaffold.py` | assert False is True |
| `test_live_submit_reject_does_not_leave_open_order` | `test_phase_c43_controlled_entry_pilot.py` | assert False is True |
| `test_mode_c_market_buy_quote_rails_and_guard_ready` | `test_phase_c_live_guard.py` | assert False is True |
| `test_mode_c_market_buy_20_100_reaches_submit_preview_without_live_call` | `test_phase_c_live_submitter.py` | assert False is True |
| `test_default_mode_is_dry_run_and_does_not_submit` | `test_phase_d3_full_residual_exit_submit_scaffold.py` | assert False is True |
| `test_submit_live_missing_submit_flag_blocks_even_with_acks` | `test_phase_d3_full_residual_exit_submit_scaffold.py` | assert False is True |
| `test_prepare_mode_a_outputs_operator_commands` | `test_prepare_mode_a_autonomous_run.py` | assert False is True |
| `test_c43_successful_submit_emits_c4_entry_order` | `test_replication_publish.py` | assert False is True |
| `test_activation_writes_profile_and_env_with_ack` | `test_sizing_only_profile_activation.py` | assert False is True |
| `test_full_poc_env_ready_and_outputs` | `test_workflow_permission_audit.py` | assert False is True |


## G2 — order_store-invariant strenger dan testfixture (11)

| Test | Module | Root cause |
|---|---|---|
| `test_one_shot_blocks_open_d3_exit_order` | `test_phase_d3_controlled_exit_pilot.py` | ValueError: live open order records require exchange_order_id |
| `test_guard_blocks_tiny_residual_close_without_exchange_order_id` | `test_phase_d3_open_exit_position_guard.py` | ValueError: live open order records require exchange_order_id |
| `test_cleanup_apply_marks_exact_one_record_rejected` | `test_phase_d3_rejected_submit_cleanup.py` | ValueError: live open order records require exchange_order_id |
| `test_cleanup_dry_run_mutates_nothing` | `test_phase_d3_rejected_submit_cleanup.py` | ValueError: live open order records require exchange_order_id |
| `test_cleanup_refuses_when_linked_position_id_mismatch` | `test_phase_d3_rejected_submit_cleanup.py` | ValueError: live open order records require exchange_order_id |
| `test_cleanup_refuses_when_reject_evidence_missing` | `test_phase_d3_rejected_submit_cleanup.py` | ValueError: live open order records require exchange_order_id |
| `test_available_plus_reserved_matches_total_managed_base_with_open_hold` | `test_phase_d3_reservation_governance.py` | ValueError: live open order records require exchange_order_id |
| `test_duplicate_actions_are_detected_and_block` | `test_phase_d3_reservation_governance.py` | ValueError: live open order records require exchange_order_id |
| `test_duplicate_labels_are_detected_and_block` | `test_phase_d3_reservation_governance.py` | ValueError: live open order records require exchange_order_id |
| `test_open_sell_order_reserving_all_base_blocks_coherence` | `test_phase_d3_reservation_governance.py` | ValueError: live open order records require exchange_order_id |
| `test_open_d3_exit_missing_exchange_order_id_still_protects_inventory_sync_close` | `test_strategy_engine_tiny_residual_phasec_pilot.py` | ValueError: live open order records require exchange_order_id |


## G3 — Verwachte configuratie-foutmeldingen afwijkend (12)

| Test | Module | Root cause |
|---|---|---|
| `test_stop_exit_apply_true_without_mode_b_ack_blocks_config_and_readiness` | `test_full_autonomous_run_readiness.py` | ValueError: ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT vereist exacte PHASE_D3_RUNTIME_SUBMIT_ACK ACK |
| `test_full_workflow_config_accepts_exact_max3x20` | `test_full_workflow_live_max3x20.py` | ValueError: DEFAULT_QUOTE_SIZE_USDC moet >= MIN_LIVE_ORDER_QUOTE_USDC zijn |
| `test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[AUTONOMOUS_MAX_OPEN_ORDERS-4-AUTONOMOUS_MAX_OPEN_ORDERS=3]` | `test_full_workflow_live_max3x20.py` | ValueError: DEFAULT_QUOTE_SIZE_USDC moet >= MIN_LIVE_ORDER_QUOTE_USDC zijn |
| `test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[ENABLE_LIVE_EXIT_ORDERS-false-ENABLE_LIVE_EXIT_ORDERS]` | `test_full_workflow_live_max3x20.py` | ValueError: DEFAULT_QUOTE_SIZE_USDC moet >= MIN_LIVE_ORDER_QUOTE_USDC zijn |
| `test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT-false-ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT]` | `test_full_workflow_live_max3x20.py` | ValueError: DEFAULT_QUOTE_SIZE_USDC moet >= MIN_LIVE_ORDER_QUOTE_USDC zijn |
| `test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[LEARNING_TO_EXECUTION_ALLOWED-true-LEARNING_TO_EXECUTION_ALLOWED]` | `test_full_workflow_live_max3x20.py` | ValueError: DEFAULT_QUOTE_SIZE_USDC moet >= MIN_LIVE_ORDER_QUOTE_USDC zijn |
| `test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[MARKET_ORDER_ENABLED-true-MARKET_ORDER_ENABLED]` | `test_full_workflow_live_max3x20.py` | ValueError: DEFAULT_QUOTE_SIZE_USDC moet >= MIN_LIVE_ORDER_QUOTE_USDC zijn |
| `test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[PHASE_C_MAX_ORDER_QUOTE-20.01-PHASE_C_MAX_ORDER_QUOTE]` | `test_full_workflow_live_max3x20.py` | ValueError: DEFAULT_QUOTE_SIZE_USDC moet >= MIN_LIVE_ORDER_QUOTE_USDC zijn |
| `test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[PHASE_D3_RUNTIME_SUBMIT_ACK--PHASE_D3_RUNTIME_SUBMIT_ACK]` | `test_full_workflow_live_max3x20.py` | ValueError: DEFAULT_QUOTE_SIZE_USDC moet >= MIN_LIVE_ORDER_QUOTE_USDC zijn |
| `test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[REPLICATION_ENABLED-true-REPLICATION_ENABLED]` | `test_full_workflow_live_max3x20.py` | ValueError: DEFAULT_QUOTE_SIZE_USDC moet >= MIN_LIVE_ORDER_QUOTE_USDC zijn |
| `test_bot_config_accepts_dynamic_min50_max100` | `test_min_max_live_order_quote.py` | ValueError: ENABLE_FULL_WORKFLOW_LIVE_MODE vereist PHASE_C_MAX_OPEN_ENTRY_ORDERS=3 |
| `test_full_workflow_live_blocks_invalid_size_or_market_flags[MARKET_ORDER_ENABLED-true-MARKET_ORDER_ENABLED]` | `test_min_max_live_order_quote.py` | ValueError: ENABLE_FULL_WORKFLOW_LIVE_MODE vereist PHASE_C_MAX_OPEN_ENTRY_ORDERS=3 |


## G4 — Paper-budget/reserveringen handhaven strenger (6)

| Test | Module | Root cause |
|---|---|---|
| `test_paper_manager_submits_to_store_without_live_order` | `test_paper_limit_order_manager_phase_b.py` | AssertionError: assert 'paper_order_intent_rejected' == 'paper_order_submitted' |
| `test_phase_b4_diagnostic_tool_runs_in_temp_mode` | `test_phase_b4_diagnostic_tool.py` | assert '"first_submit": "paper_order_submitted"' in 'Phase-B.4 paper budget/reserved-balance diagnose\n{\n  "m |
| `test_paper_manager_rejects_buy_when_reserved_quote_exhausts_balance` | `test_phase_b4_paper_budget_reserved_balances.py` | AssertionError: assert 'paper_order_intent_rejected' == 'paper_order_submitted' |
| `test_paper_manager_rejects_duplicate_entry_order` | `test_phase_b4_paper_budget_reserved_balances.py` | AssertionError: assert 'paper_order_intent_rejected' == 'paper_order_submitted' |
| `test_paper_new_order_budget_blocks_third_order` | `test_phase_b4_paper_budget_reserved_balances.py` | AssertionError: assert 'paper_order_intent_rejected' == 'paper_order_submitted' |
| `test_b4_budget_reserved_tool_runs_directly_without_pythonpath` | `test_phase_b5_ops_tools.py` | assert 'paper_order_phase_b4_rejected' in 'Phase-B.4 paper budget/reserved-balance diagnose\n{\n  "mode": "tem |


## G5 — Prompttekst gewijzigd t.o.v. testverwachting (3)

| Test | Module | Root cause |
|---|---|---|
| `test_final_risk_firewall_remains_absolute` | `test_prompts_competitive_bounded_alpha.py` | AssertionError: assert 'risk/firewall may reduce it' in '\nYou are the GPT-5.5 trade planner for a Coinbase SP |
| `test_prompts_still_demand_strict_json` | `test_prompts_competitive_bounded_alpha.py` | AssertionError: assert 'Return only strict JSON' in '\nYou are the final decision engine for a Coinbase SPOT c |
| `test_spot_only_no_naked_shorts_and_market_orders_not_encouraged` | `test_prompts_competitive_bounded_alpha.py` | AssertionError: assert 'side=BUY, size_quote between 20.00 and 100.00 USDC' in '\nYou are the final decision e |


## G6 — Operator-bashscripts / hardcoded serverpad (6)

| Test | Module | Root cause |
|---|---|---|
| `test_wrapper_requires_exact_ack_for_actual_submit_true` | `test_all_ticker_operator_live_start_gate.py` | subprocess.CalledProcessError: Command '['tools/operator_all_ticker_tiny_env.sh', 'bash', '-lc', 'printf \'%s\ |
| `test_workflow_review_tool_writes_audit_reports` | `test_full_workflow_critical_review.py` | FileNotFoundError: [Errno 2] No such file or directory: '/root/apps/Crypto/coinbase_bot' |
| `test_operator_script_exact_ack_enables_full_workflow_caps_and_exits` | `test_full_workflow_live_max3x20.py` | subprocess.CalledProcessError: Command '['bash', 'tools/operator_full_workflow_live_max3x20_env.sh', 'env']' r |
| `test_operator_script_requires_exact_ack_for_live_exits_and_d3_submit` | `test_full_workflow_live_max3x20.py` | subprocess.CalledProcessError: Command '['bash', 'tools/operator_full_workflow_live_max3x20_env.sh', 'env']' r |
| `test_governance_bundle_cli_stdout_is_safe` | `test_phase_d6_governance_evidence_bundle.py` | subprocess.CalledProcessError: Command '['/tmp/claude-0/-home-user-open-jarvis/c37dc3b2-7d33-52e6-82c9-97b37a1 |
| `test_live_test_readiness_cli_stdout_is_safe` | `test_phase_d6_live_test_readiness.py` | subprocess.CalledProcessError: Command '['/tmp/claude-0/-home-user-open-jarvis/c37dc3b2-7d33-52e6-82c9-97b37a1 |


## G7 — Entry/exit-beleidslabels gewijzigd (14)

| Test | Module | Root cause |
|---|---|---|
| `test_idempotent_rerun_does_not_submit_second_sell` | `test_execute_controlled_btc_position_close.py` | AssertionError: assert 'controlled_c...ply_performed' == 'controlled_c...empotent_noop' |
| `test_repeated_reconcile_run_stays_filled_without_live_action` | `test_execute_controlled_btc_position_close.py` | AssertionError: assert 'controlled_c...ply_performed' == 'controlled_c...empotent_noop' |
| `test_valid_fresh_judge_buy_and_deterministic_risk_can_become_phase_c_ready` | `test_full_bot_fresh_judge_risk_evidence_runner.py` | AssertionError: assert [] == ['XRP-USDC'] |
| `test_real_judge_approval_can_feed_deterministic_risk_and_phase_c_preview` | `test_full_bot_real_fresh_review_runner.py` | AssertionError: assert [] == ['XRP-USDC'] |
| `test_live_submit_places_exactly_one_order_and_keeps_lifecycle_preview` | `test_phase_c43_controlled_entry_pilot.py` | AssertionError: assert 'controlled_entry_blocked' == 'controlled_e...der_submitted' |
| `test_one_shot_arming_allows_d31_readiness_without_env_mutation` | `test_phase_c43_controlled_entry_pilot.py` | AssertionError: assert 'controlled_entry_blocked' == 'controlled_e...der_submitted' |
| `test_live_context_preview_match_stays_ready_no_submit` | `test_phase_d3_controlled_exit_pilot.py` | AssertionError: assert 'd3_no_ready_...executor_plan' == 'd3_controlle...ady_no_submit' |
| `test_inventory_sync_closed_list_stays_empty_when_guard_blocks` | `test_phase_d3_open_exit_position_guard.py` | AssertionError: assert [] == ['BTC-USDC'] |
| `test_inventory_sync_exchange_positions_keeps_recovered_phase_c43_pilot_open` | `test_strategy_engine_tiny_residual_phasec_pilot.py` | AssertionError: assert [] == ['BTC-USDC'] |
| `test_inventory_sync_keeps_position_open_when_matching_open_d3_exit_exists` | `test_strategy_engine_tiny_residual_phasec_pilot.py` | KeyError: 'tiny_residual_close_skip_reason' |
| `test_open_d3_exit_for_other_position_does_not_protect_inventory_sync_close` | `test_strategy_engine_tiny_residual_phasec_pilot.py` | AssertionError: assert [] == ['BTC-USDC'] |
| `test_open_d3_exit_with_recovered_linked_position_prevents_inventory_sync_close` | `test_strategy_engine_tiny_residual_phasec_pilot.py` | KeyError: 'tiny_residual_close_skip_reason' |
| `test_position_action_close_keeps_phase_c43_tiny_residual_open_for_governance` | `test_strategy_engine_tiny_residual_phasec_pilot.py` | AssertionError: assert 'd3_controlle...ked_by_policy' == 'position_act...al_governance' |
| `test_position_action_close_still_closes_non_phase_c43_dust_position` | `test_strategy_engine_tiny_residual_phasec_pilot.py` | AssertionError: assert 'd3_controlle...ked_by_policy' == 'position_clo..._min_notional' |


## G8 — Overig: gevolg van geblokkeerde voorgaande stap (21)

| Test | Module | Root cause |
|---|---|---|
| `test_run_report_counts_fixture_logs` | `test_autonomous_live_run_report.py` | assert 0 == 1 |
| `test_run_report_recommends_continue_mode_a_on_clean_run` | `test_autonomous_live_run_report.py` | AssertionError: assert 'bad' == 'good' |
| `test_status_detects_pid_mismatch` | `test_autonomous_live_run_status.py` | AssertionError: assert 'blocked' == 'warning' |
| `test_existing_phase_c_guard_blockers_remain_without_evidence` | `test_full_bot_near_miss_phase_c_review.py` | AssertionError: assert 'fresh_judge_buy_approval_missing' in ['amount_cap:precision:base_increment_missing', ' |
| `test_promoted_candidate_requires_fresh_judge_buy_and_live_risk_approval` | `test_full_bot_near_miss_phase_c_review.py` | assert 0 == 1 |
| `test_fill_to_position_happy_path_creates_position_and_clears_reserved_quote` | `test_full_pipeline_contracts.py` | IndexError: list index out of range |
| `test_market_order_mode_c_disabled_is_valid_but_not_ready` | `test_market_order_mode_c_governance.py` | AssertionError: assert ['market_orde...s_not_50_100'] == [] |
| `test_order_intent_builds_limit_buy_from_trade_plan` | `test_paper_limit_order_manager_phase_b.py` | AssertionError: assert 'failed' == 'planned' |
| `test_c33_builds_final_preflight_snapshot_with_valid_candidate_and_no_submit` | `test_phase_c33_candidate_preflight.py` | AssertionError: assert 'blocked' == 'final_prefli...ady_no_submit' |
| `test_c35_reports_preflight_ready_when_c34_and_c33_are_green` | `test_phase_c35_candidate_watcher.py` | AssertionError: assert 'candidates_b...ed_or_waiting' == 'preflight_ready_no_submit' |
| `test_strategy_engine_direct_c43_bridge_does_not_submit_when_live_exits_enabled` | `test_phase_c43_strategy_engine_direct_bridge.py` | KeyError: 'live_order_submitted' |
| `test_strategy_engine_direct_c43_bridge_submits_without_paper_manager` | `test_phase_c43_strategy_engine_direct_bridge.py` | KeyError: 'strategy_engine_direct_bridge' |
| `test_mode_c_market_orders_false_remains_valid_disabled` | `test_phase_c_live_guard.py` | AssertionError: assert ['market_orde...s_not_50_100'] == [] |
| `test_d2_default_tp2_is_above_tp1_when_tp1_requirement_is_high` | `test_phase_d23_hardening_v1.py` | StopIteration |
| `test_live_context_preview_submit_reject_stays_not_submitted` | `test_phase_d3_controlled_exit_pilot.py` | TypeError: 'NoneType' object is not subscriptable |
| `test_live_context_preview_uses_exchange_rules_and_changes_fingerprint` | `test_phase_d3_controlled_exit_pilot.py` | AssertionError: assert '0' == '0.0000648950' |
| `test_one_shot_success_path_calls_existing_d3_submit_once_with_fake_coinbase_client_only` | `test_phase_d3_controlled_exit_pilot.py` | assert 0 == 1 |
| `test_full_residual_prep_ready_with_live_base_and_rules` | `test_phase_d3_full_residual_exit_prep.py` | AssertionError: assert 'd3_full_resi..._prep_blocked' == 'd3_full_resi...al_prep_ready' |
| `test_full_residual_candidate_is_accepted_for_dry_run_review` | `test_phase_d3_full_residual_exit_submit_scaffold.py` | AssertionError: assert ['d3_readines...tion_missing'] == [] |
| `test_planner_builds_starter_probe_with_soft_bearish_warnings` | `test_preselection_calibration.py` | assert 50.0 == 20.0 |
| `test_sizing_tool_writes_candidate_and_report` | `test_sizing_only_profile_activation.py` | assert 2 == 0 |


## G9 — Onvolledige testdubbel (mist methode van echte klasse) (1)

| Test | Module | Root cause |
|---|---|---|
| `test_d31_includes_d32_health_and_blocks_when_recent_corrupt` | `test_phase_d32_llm_pre_live_health.py` | AttributeError: '_EmptyOrderStore' object has no attribute 'all_orders'. Did you mean: 'list_orders'? |
