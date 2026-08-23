# D.5 Execution Metrics Scaffold

Timestamp: `2026-05-29`

## Purpose

This scaffold adds an offline/report-only D.5 metrics layer above D.3/D.4 lifecycle data. It analyzes completed lifecycle events, fill/no-fill outcomes, slippage, fees, latency and realized-vs-planned edge. It never calls Coinbase, never performs live action, never writes trading state and never allows learning-to-execution.

## Inputs

- lifecycle event or order record fixture
- D.2/D.3 plan fields:
  - `planned_entry_price`
  - `planned_exit_price`
  - `planned_size_base`
  - `exit_label`
- optional market reference snapshots:
  - `decision_mid`
  - `decision_best_bid`
  - `decision_best_ask`
  - `fill_reference_mid`
- fills:
  - `filled_base`
  - `filled_quote`
  - `avg_fill_price`
  - `fees`
  - `fill_count`
  - `first_fill_at`
  - `final_fill_at`
- timestamps:
  - `order_created_at`
  - `submitted_at`
  - `first_seen_open_at`
  - terminal timestamps such as `closed_at`, `filled_at`, `cancelled_at`, `expired_at`, `rejected_at`
- lifecycle status:
  - `OPEN/no-fill`
  - `PARTIAL`
  - `FILLED`
  - `CANCELLED`
  - `EXPIRED`
  - `REJECTED`
- optional D.4 decision:
  - `keep_open`
  - `preview_reprice_candidate`
  - `dry_run_cancel_replace_plan_ready`
  - `no_op_keep_open`

## Outputs

- `status`
- `lifecycle_status`
- `is_complete_lifecycle_event`
- `is_training_eligible=false` by default
- `fill_latency_seconds`
- `no_fill_duration_seconds`
- `realized_exit_price`
- `planned_exit_price`
- `realized_vs_planned_edge_pct`
- `slippage_vs_decision_mid_pct`
- `slippage_vs_best_bid_or_ask_pct`
- `fee_quote`
- `fee_bps_estimate`
- `fill_quality_label`
- `no_fill_reason_label`
- `stale_order_age_seconds`
- `cancel_replace_outcome`
- `learning_to_execution_allowed=false`
- `required_future_gate_for_execution`
- `blockers`
- `warnings`
- `no_coinbase_call=true`
- `no_live_action=true`
- `state_write_performed=false`

## Metrics Definitions

- `realized_exit_price`: `avg_fill_price`, or `filled_quote / filled_base` when average price is missing.
- `realized_vs_planned_edge_pct`: `(realized_exit_price - planned_exit_price) / planned_exit_price`.
- `slippage_vs_decision_mid_pct`: `(realized_exit_price - decision_mid) / decision_mid`.
- `slippage_vs_best_bid_or_ask_pct`: sell-side comparison to `decision_best_bid`.
- `fee_bps_estimate`: `fees / filled_quote * 10000`.
- `fill_latency_seconds`: `first_fill_at - submitted_at`.
- `no_fill_duration_seconds`: terminal/no-fill timestamp or report time minus first open observation.
- `stale_order_age_seconds`: terminal timestamp or report time minus first open observation.

## Training Eligibility Rules

- `OPEN/open` zero fills is not training eligible.
- `PARTIAL` without terminal outcome is not training eligible.
- `FILLED` is metrics-complete.
- `CANCELLED`, `EXPIRED`, or `REJECTED` with zero fills is terminal no-fill and metrics-complete, but not automatically bad.
- Missing market reference does not crash the report; it emits warnings and leaves partial slippage metrics blank.

## Learning-To-Execution Gate

D.5 is report-only. `learning_to_execution_allowed=false` is hard-coded for this scaffold. Any future execution influence requires a separate feature gate, operator approval, ACK, rollback plan and test coverage.

## Test Matrix

| Scenario | Expected result |
| --- | --- |
| current `OPEN/no-fill` TP1 | `no_fill_open`, not training eligible |
| filled above planned | `filled_good`, positive realized-vs-planned edge |
| filled below planned | `filled_bad`, no automatic action |
| partial still open | `partial`, not training eligible |
| cancelled zero fill | `terminal_no_fill`, metrics-complete |
| expired zero fill | `terminal_no_fill` |
| rejected zero fill | `terminal_no_fill` |
| missing market snapshot | warning, no crash |
| fee present | fee bps estimate |
| learning-to-execution gate | always false, report-only |
| CLI fixture read | no state writes |
| fake client write trap | no write methods called |

## Next Step

Keep D.5 analysis-only. Future work can add more fixture shapes or aggregate reports, but must not change D.2/D.3/D.4 parameters or trigger live execution.
