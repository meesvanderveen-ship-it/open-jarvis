# Learning/Backlearning Inventory

Generated: `2026-06-12T20:49:14Z`

| Component | Status | Runtime hook | Candidate | Risk | Action |
|---|---:|---:|---:|---|---|
| trade_reflection | present | True | False | medium | keep_report_only_and_feed_compact_orchestrator_context |
| decision_outcome_tracker | present | True | False | medium | keep_report_only_and_feed_compact_orchestrator_context |
| execution_outcome_tracker | present | True | False | medium | keep_report_only_and_feed_compact_orchestrator_context |
| phase_d5_execution_metrics | present | False | False | medium | keep_report_only_and_feed_compact_orchestrator_context |
| phase_d5_learning_log | present | False | False | medium | keep_report_only_and_feed_compact_orchestrator_context |
| phase_d6_backlearning | present | False | True | medium | keep_report_only_and_feed_compact_orchestrator_context |
| phase_d6_walk_forward_oos_overfitting | present | False | False | medium | keep_report_only_and_feed_compact_orchestrator_context |
| paper_pending_intents | present | True | False | medium | keep_report_only_and_feed_compact_orchestrator_context |
| approved_parameter_profile | present | True | False | medium_ack_gated | use_only_hash_ack_gated_activation |
| balanced_start_profiles | present | False | True | low | keep_report_only_and_feed_compact_orchestrator_context |
| live_learning_sidecar | present | False | True | low | keep_report_only_and_feed_compact_orchestrator_context |
| shadow_parameter_packs | present | False | True | low | keep_report_only_and_feed_compact_orchestrator_context |
| historical_candle_backtest | present | False | False | medium | keep_report_only_and_feed_compact_orchestrator_context |
| cost_aware_learning | present | False | True | low | keep_report_only_and_feed_compact_orchestrator_context |
| live_learning_orchestrator | present | True | False | low | keep_report_only_and_feed_compact_orchestrator_context |

Direct learning-to-execution flags remain unnecessary; activation is via approved profile hash ACK.
