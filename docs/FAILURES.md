# Testfailures: actueel register

Gegenereerd uit een echte testrun met `tools/build_failure_register.py`.
Niet met de hand bijgehouden, dus niet stiekem verouderd.

| | |
|---|---|
| Gemeten op | 2026-09-01 |
| Python | 3.11.15 (Linux) |
| Commando | `python -m pytest -q` |
| Resultaat | **2846 geslaagd, 103 gefaald, 2 overgeslagen** |

**Alle 103 failures hieronder bestonden al in de aangeleverde ZIP.**
Er zijn geen nieuwe failures geintroduceerd. Twee failures uit de ZIP zijn
opgelost; die staan onderaan.

## Waarom deze niet 'gerepareerd' zijn

Verreweg de meeste zijn geen defect maar een *werkende veiligheidsmaatregel*.
De bot wordt geleverd met elke live-handelspoort dicht: geen live orders, geen
market orders, geen replicatie, geen automatische parametermutatie. Een test
die zo'n poort open verwacht, faalt dan per definitie.

Die tests groen maken zou neerkomen op het openzetten van die poorten. Dat is
het tegenovergestelde van een veilige levering, en is bewust niet gedaan.

| Oordeel | Aantal | Betekenis |
|---|---|---|
| **GATE** | 93 | Een veiligheidsmaatregel doet zijn werk. Niet repareren. |
| **DRIFT** | 5 | Code en testverwachting zijn uit elkaar gelopen. Vereist een inhoudelijk oordeel over de handelsstrategie. |
| **OMGEVING** | 5 | Faalt door een ontbrekende `.env`, niet door de code. |

## Groepen

### Live-gate staat dicht in de veilige standaardconfiguratie

**74 tests — oordeel: GATE**

De bot wordt geleverd met elke live-handelspoort dicht. Deze tests verwachten een toestand die alleen ontstaat als zo'n poort openstaat.

Typische foutregel:

```
assert 0 == 1
```

<details>
<summary>Alle tests in deze groep</summary>

- `tests/test_autonomous_live_run_report.py::test_run_report_counts_fixture_logs`
- `tests/test_autonomous_live_run_report.py::test_run_report_recommends_continue_mode_a_on_clean_run`
- `tests/test_autonomous_live_run_status.py::test_status_detects_pid_mismatch`
- `tests/test_autonomous_live_run_status.py::test_status_mode_a_ready_with_mode_b_disabled`
- `tests/test_execute_controlled_btc_position_close.py::test_idempotent_rerun_does_not_submit_second_sell`
- `tests/test_execute_controlled_btc_position_close.py::test_repeated_reconcile_run_stays_filled_without_live_action`
- `tests/test_full_autonomous_run_readiness.py::test_current_open_d3_baseline_ready_with_stop_exit_preview_only`
- `tests/test_full_autonomous_run_readiness.py::test_mode_b_readiness_requires_exact_ack`
- `tests/test_full_autonomous_run_readiness.py::test_mode_c_market_orders_exact_ack_replication_false_ready`
- `tests/test_full_bot_fresh_judge_risk_evidence_runner.py::test_valid_fresh_judge_buy_and_deterministic_risk_can_become_phase_c_ready`
- `tests/test_full_bot_near_miss_phase_c_review.py::test_adapter_report_can_consume_promoted_candidate_in_dry_run_and_submit_remains_ack_gated`
- `tests/test_full_bot_near_miss_phase_c_review.py::test_existing_phase_c_guard_blockers_remain_without_evidence`
- `tests/test_full_bot_near_miss_phase_c_review.py::test_promoted_candidate_requires_fresh_judge_buy_and_live_risk_approval`
- `tests/test_full_bot_real_fresh_review_runner.py::test_real_judge_approval_can_feed_deterministic_risk_and_phase_c_preview`
- `tests/test_full_pipeline_contracts.py::test_fill_to_position_happy_path_creates_position_and_clears_reserved_quote`
- `tests/test_full_pipeline_health.py::test_full_pipeline_health_report_uses_existing_reports_and_stays_red`
- `tests/test_full_poc_workflow_readiness.py::test_full_poc_allows_default_quote_50_inside_live_rails`
- `tests/test_full_poc_workflow_readiness.py::test_full_poc_missing_mode_c_ack_does_not_block_orderbook_only_route`
- `tests/test_full_poc_workflow_readiness.py::test_full_poc_with_mode_b_mode_c_and_replication_false_is_ready`
- `tests/test_full_workflow_live_max3x20.py::test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[AUTONOMOUS_MAX_OPEN_ORDERS-4-AUTONOMOUS_MAX_OPEN_ORDERS=3]`
- `tests/test_full_workflow_live_max3x20.py::test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[ENABLE_LIVE_EXIT_ORDERS-false-ENABLE_LIVE_EXIT_ORDERS]`
- `tests/test_full_workflow_live_max3x20.py::test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT-false-ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT]`
- `tests/test_full_workflow_live_max3x20.py::test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[LEARNING_TO_EXECUTION_ALLOWED-true-LEARNING_TO_EXECUTION_ALLOWED]`
- `tests/test_full_workflow_live_max3x20.py::test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[MARKET_ORDER_ENABLED-true-MARKET_ORDER_ENABLED]`
- `tests/test_full_workflow_live_max3x20.py::test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[PHASE_C_MAX_ORDER_QUOTE-20.01-PHASE_C_MAX_ORDER_QUOTE]`
- `tests/test_full_workflow_live_max3x20.py::test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[PHASE_D3_RUNTIME_SUBMIT_ACK--PHASE_D3_RUNTIME_SUBMIT_ACK]`
- `tests/test_full_workflow_live_max3x20.py::test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps[REPLICATION_ENABLED-true-REPLICATION_ENABLED]`
- `tests/test_full_workflow_live_max3x20.py::test_full_workflow_entry_submitter_can_run_with_d3_exit_flags_enabled`
- `tests/test_llm_cost_ledger.py::test_record_llm_call_writes_redacted_metadata_row`
- `tests/test_market_order_mode_c_governance.py::test_market_buy_quote_rails_and_preview_no_live_call`
- `tests/test_market_order_mode_c_governance.py::test_market_order_mode_c_disabled_is_valid_but_not_ready`
- `tests/test_market_order_mode_c_governance.py::test_market_order_mode_c_requires_exact_ack_and_replication_off`
- `tests/test_min_max_live_order_quote.py::test_full_workflow_live_blocks_invalid_size_or_market_flags[MARKET_ORDER_ENABLED-true-MARKET_ORDER_ENABLED]`
- `tests/test_paper_limit_order_manager_phase_b.py::test_order_intent_builds_limit_buy_from_trade_plan`
- `tests/test_phase_c21_live_submit_dry_run_audit.py::test_phase_c21_simulate_ready_guard_still_blocks_actual_submit`
- `tests/test_phase_c2_live_submit_scaffold.py::test_c2_payload_builder_creates_base_sized_limit_preview_without_submit`
- `tests/test_phase_c2_live_submit_scaffold.py::test_c2_submit_branch_requires_explicit_submit_argument_and_extra_flag`
- `tests/test_phase_c31_go_no_go.py::test_c31_ready_for_human_review_when_c30_runtime_and_guard_are_green_but_actual_submit_false`
- `tests/test_phase_c32_staged_pilot_config.py::test_c32_full_report_ready_for_human_review_under_staged_config_with_candidate`
- `tests/test_phase_c33_candidate_preflight.py::test_c33_builds_final_preflight_snapshot_with_valid_candidate_and_no_submit`
- `tests/test_phase_c34_candidate_snapshot.py::test_c34_report_can_extract_from_logs_and_reach_final_preflight_ready_with_real_risk`
- `tests/test_phase_c35_candidate_watcher.py::test_c35_reports_preflight_ready_when_c34_and_c33_are_green`
- `tests/test_phase_c38_final_pilot_executor_scaffold.py::test_c38_all_final_hardlocks_use_submitter_with_fake_client_only`
- `tests/test_phase_c43_controlled_entry_pilot.py::test_live_submit_places_exactly_one_order_and_keeps_lifecycle_preview`
- `tests/test_phase_c43_controlled_entry_pilot.py::test_live_submit_reject_does_not_leave_open_order`
- `tests/test_phase_c43_controlled_entry_pilot.py::test_one_shot_arming_allows_d31_readiness_without_env_mutation`
- `tests/test_phase_c43_strategy_engine_direct_bridge.py::test_strategy_engine_direct_c43_bridge_does_not_submit_when_live_exits_enabled`
- `tests/test_phase_c43_strategy_engine_direct_bridge.py::test_strategy_engine_direct_c43_bridge_submits_without_paper_manager`
- `tests/test_phase_c_live_guard.py::test_mode_c_market_buy_quote_rails_and_guard_ready`
- `tests/test_phase_c_live_guard.py::test_mode_c_market_orders_false_remains_valid_disabled`
- `tests/test_phase_c_live_submitter.py::test_mode_c_market_buy_20_100_reaches_submit_preview_without_live_call`
- `tests/test_phase_d23_hardening_v1.py::test_d2_default_tp2_is_above_tp1_when_tp1_requirement_is_high`
- `tests/test_phase_d3_controlled_exit_pilot.py::test_live_context_preview_match_stays_ready_no_submit`
- `tests/test_phase_d3_controlled_exit_pilot.py::test_live_context_preview_submit_reject_stays_not_submitted`
- `tests/test_phase_d3_controlled_exit_pilot.py::test_live_context_preview_uses_exchange_rules_and_changes_fingerprint`
- `tests/test_phase_d3_controlled_exit_pilot.py::test_one_shot_success_path_calls_existing_d3_submit_once_with_fake_coinbase_client_only`
- `tests/test_phase_d3_full_residual_exit_prep.py::test_full_residual_prep_ready_with_live_base_and_rules`
- `tests/test_phase_d3_full_residual_exit_submit_scaffold.py::test_default_mode_is_dry_run_and_does_not_submit`
- `tests/test_phase_d3_full_residual_exit_submit_scaffold.py::test_full_residual_candidate_is_accepted_for_dry_run_review`
- `tests/test_phase_d3_full_residual_exit_submit_scaffold.py::test_submit_live_missing_submit_flag_blocks_even_with_acks`
- `tests/test_phase_d3_open_exit_position_guard.py::test_inventory_sync_closed_list_stays_empty_when_guard_blocks`
- `tests/test_prepare_mode_a_autonomous_run.py::test_prepare_mode_a_outputs_operator_commands`
- `tests/test_preselection_calibration.py::test_planner_builds_starter_probe_with_soft_bearish_warnings`
- `tests/test_replication_publish.py::test_c43_successful_submit_emits_c4_entry_order`
- `tests/test_sizing_only_profile_activation.py::test_activation_writes_profile_and_env_with_ack`
- `tests/test_sizing_only_profile_activation.py::test_sizing_tool_writes_candidate_and_report`
- `tests/test_strategy_engine_tiny_residual_phasec_pilot.py::test_inventory_sync_exchange_positions_keeps_recovered_phase_c43_pilot_open`
- `tests/test_strategy_engine_tiny_residual_phasec_pilot.py::test_inventory_sync_keeps_position_open_when_matching_open_d3_exit_exists`
- `tests/test_strategy_engine_tiny_residual_phasec_pilot.py::test_open_d3_exit_for_other_position_does_not_protect_inventory_sync_close`
- `tests/test_strategy_engine_tiny_residual_phasec_pilot.py::test_open_d3_exit_missing_exchange_order_id_still_protects_inventory_sync_close`
- `tests/test_strategy_engine_tiny_residual_phasec_pilot.py::test_open_d3_exit_with_recovered_linked_position_prevents_inventory_sync_close`
- `tests/test_strategy_engine_tiny_residual_phasec_pilot.py::test_position_action_close_keeps_phase_c43_tiny_residual_open_for_governance`
- `tests/test_strategy_engine_tiny_residual_phasec_pilot.py::test_position_action_close_still_closes_non_phase_c43_dust_position`
- `tests/test_workflow_permission_audit.py::test_full_poc_env_ready_and_outputs`

</details>

### Veiligheidsinvariant strenger dan de testfixture

**10 tests — oordeel: GATE**

order_store weigert een live openstaande order zonder exchange_order_id. Zonder dat nummer zou de bot denken dat er een order op de beurs staat die hij nooit kan opzoeken of annuleren. De fixtures in deze tests maken precies zo'n record aan.

Typische foutregel:

```
ValueError: live open order records require exchange_order_id
```

<details>
<summary>Alle tests in deze groep</summary>

- `tests/test_phase_d3_controlled_exit_pilot.py::test_one_shot_blocks_open_d3_exit_order`
- `tests/test_phase_d3_open_exit_position_guard.py::test_guard_blocks_tiny_residual_close_without_exchange_order_id`
- `tests/test_phase_d3_rejected_submit_cleanup.py::test_cleanup_apply_marks_exact_one_record_rejected`
- `tests/test_phase_d3_rejected_submit_cleanup.py::test_cleanup_dry_run_mutates_nothing`
- `tests/test_phase_d3_rejected_submit_cleanup.py::test_cleanup_refuses_when_linked_position_id_mismatch`
- `tests/test_phase_d3_rejected_submit_cleanup.py::test_cleanup_refuses_when_reject_evidence_missing`
- `tests/test_phase_d3_reservation_governance.py::test_available_plus_reserved_matches_total_managed_base_with_open_hold`
- `tests/test_phase_d3_reservation_governance.py::test_duplicate_actions_are_detected_and_block`
- `tests/test_phase_d3_reservation_governance.py::test_duplicate_labels_are_detected_and_block`
- `tests/test_phase_d3_reservation_governance.py::test_open_sell_order_reserving_all_base_blocks_coherence`

</details>

### Paper-budget handhaaft strenger dan de test verwacht

**6 tests — oordeel: GATE**

De papieren orderlaag weigert orders die de test wel geplaatst wil zien (budget uitgeput, dubbele entry). Strenger dan verwacht is hier de veilige kant.

Typische foutregel:

```
AssertionError: assert 'paper_order_intent_rejected' == 'paper_order_submitted'
```

<details>
<summary>Alle tests in deze groep</summary>

- `tests/test_paper_limit_order_manager_phase_b.py::test_paper_manager_submits_to_store_without_live_order`
- `tests/test_phase_b4_diagnostic_tool.py::test_phase_b4_diagnostic_tool_runs_in_temp_mode`
- `tests/test_phase_b4_paper_budget_reserved_balances.py::test_paper_manager_rejects_buy_when_reserved_quote_exhausts_balance`
- `tests/test_phase_b4_paper_budget_reserved_balances.py::test_paper_manager_rejects_duplicate_entry_order`
- `tests/test_phase_b4_paper_budget_reserved_balances.py::test_paper_new_order_budget_blocks_third_order`
- `tests/test_phase_b5_ops_tools.py::test_b4_budget_reserved_tool_runs_directly_without_pythonpath`

</details>

### Operator-shellscript weigert zonder .env

**5 tests — oordeel: OMGEVING**

De scripts melden 'refusing to build operator override environment' als er geen .env is. Dat is correct defensief gedrag; in een omgeving met een .env draaien ze door.

Typische foutregel:

```
subprocess.CalledProcessError: Command '['tools/operator_all_ticker_tiny_env.sh', 'bash', '-lc', 'printf \'%s\' "$ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT:$ENABLE_
```

<details>
<summary>Alle tests in deze groep</summary>

- `tests/test_all_ticker_operator_live_start_gate.py::test_wrapper_requires_exact_ack_for_actual_submit_true`
- `tests/test_full_workflow_live_max3x20.py::test_operator_script_exact_ack_enables_full_workflow_caps_and_exits`
- `tests/test_full_workflow_live_max3x20.py::test_operator_script_requires_exact_ack_for_live_exits_and_d3_submit`
- `tests/test_phase_d6_governance_evidence_bundle.py::test_governance_bundle_cli_stdout_is_safe`
- `tests/test_phase_d6_live_test_readiness.py::test_live_test_readiness_cli_stdout_is_safe`

</details>

### Prompttekst afgeweken van de testverwachting

**5 tests — oordeel: DRIFT**

De prompts voor de LLM-laag zijn gewijzigd; de tests controleren nog op de oude formuleringen. Welke van de twee klopt is een inhoudelijk oordeel over de handelsstrategie, niet over de installatie.

Typische foutregel:

```
AssertionError: assert {'DEEPSEEK_PR...ANNER_PROMPT'} == {'BEAR_PROMPT..._PROMPT', ...}
```

<details>
<summary>Alle tests in deze groep</summary>

- `dashboard/backend/tests/test_prompt_extraction.py::test_extracts_known_prompt_templates`
- `tests/test_build_multi_agent_prompt_audit.py::test_prompt_inventory_finds_all_prompts_py_templates`
- `tests/test_prompts_competitive_bounded_alpha.py::test_final_risk_firewall_remains_absolute`
- `tests/test_prompts_competitive_bounded_alpha.py::test_prompts_still_demand_strict_json`
- `tests/test_prompts_competitive_bounded_alpha.py::test_spot_only_no_naked_shorts_and_market_orders_not_encouraged`

</details>

### Configuratie-gate weigert de testconfiguratie

**3 tests — oordeel: GATE**

BotConfig.validate() weigert combinaties die de test wel opvoert. De validatie faalt bewust dicht: liever niet starten dan starten met een ordergrootte buiten de ingestelde grenzen.

Typische foutregel:

```
ValueError: ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT vereist exacte PHASE_D3_RUNTIME_SUBMIT_ACK ACK
```

<details>
<summary>Alle tests in deze groep</summary>

- `tests/test_full_autonomous_run_readiness.py::test_stop_exit_apply_true_without_mode_b_ack_blocks_config_and_readiness`
- `tests/test_full_workflow_live_max3x20.py::test_full_workflow_config_accepts_exact_max3x20`
- `tests/test_min_max_live_order_quote.py::test_bot_config_accepts_dynamic_min50_max100`

</details>

## Opgelost tijdens deze audit

| Test | Wat er mis was |
|---|---|
| `tests/test_full_workflow_critical_review.py::test_workflow_review_tool_writes_audit_reports` | De test deed `monkeypatch.chdir("/root/apps/Crypto/coinbase_bot")` — een map die alleen op één server bestaat. Overal elders een `FileNotFoundError`. Nu een tijdelijke map. |
| `tests/test_phase_d32_llm_pre_live_health.py::test_d31_includes_d32_health_and_blocks_when_recent_corrupt` | De testdubbel `_EmptyOrderStore` miste `all_orders()`, die de echte `OrderStore` wel heeft en die de code onder test aanroept. De test liep stuk op een `AttributeError` voordat zijn eigenlijke assertie aan bod kwam. |

Beide waren aantoonbaar fouten in de test zelf, niet in de productiecode. Geen
enkele test is aangepast om een groene score te halen.

## Hoe je dit register bijwerkt

```
.venv\Scripts\python tools\build_failure_register.py --run
```

Elke failure die na een run niet in dit bestand staat, is nieuw en verdient
onderzoek voordat je hem als bekend afdoet.
