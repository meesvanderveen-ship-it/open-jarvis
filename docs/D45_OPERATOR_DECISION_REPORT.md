# D.4/D.5 Operator Decision Report

Timestamp: `2026-05-29`

## Purpose

This report combines D.3 lifecycle evidence, D.4 trailing preview, D.4 dry-run cancel/replace planning and D.5 execution metrics into one offline operator decision summary. It recommends the next safe operator action without calling Coinbase, cancelling, replacing, submitting, applying lifecycle evidence, writing trading state or allowing learning-to-execution.

## Inputs

- local D.3 lifecycle or order fixture
- D.4 trailing preview fixture
- D.4 dry-run cancel/replace planner fixture
- D.5 execution metrics fixture
- optional operator mode:
  - `wait_only`
  - `decision_only`
  - `future_reprice_consideration`

## Outputs

- `status`
- `active_order_summary`
- `lifecycle_branch`
- `d4_preview_summary`
- `d4_planner_summary`
- `d5_metrics_summary`
- `recommended_operator_action`
- `reason`
- `blockers`
- `warnings`
- `required_future_ack`
- `no_coinbase_call=true`
- `no_live_action=true`
- `state_write_performed=false`
- `learning_to_execution_allowed=false`

## Decision Rules

1. `OPEN/open` with zero fills and no D.4 candidate recommends `wait_for_trigger`.
2. `OPEN/open` with D.4 candidate and planner ready recommends `consider_reprice_decision`; future ACK is required and no live action is allowed.
3. `PARTIAL` or `FILLED` evidence recommends `prepare_fill_lifecycle_apply`.
4. `CANCELLED`, `EXPIRED`, or `REJECTED` evidence recommends `prepare_terminal_closeout`.
5. Duplicate, oversell or reservation mismatch blockers recommend `blocked_p0_review_required`.
6. D.5 may inform the reason, but never authorizes execution. `learning_to_execution_allowed=false` always.

## Safety Gates

- no Coinbase calls
- no cancel/replace/submit
- no lifecycle apply
- no trading-state write
- no service restart
- no dependency changes
- no learning-to-execution
- D.3 lifecycle evidence and P0 blockers override D.4/D.5 reports

## Test Matrix

| Scenario | Expected action |
| --- | --- |
| OPEN/no-fill + D.4 keep open + D.5 no-fill | `wait_for_trigger` |
| OPEN/no-fill + D.4 candidate + planner ready | `consider_reprice_decision` |
| PARTIAL/FILLED evidence | `prepare_fill_lifecycle_apply` |
| CANCELLED/EXPIRED/REJECTED evidence | `prepare_terminal_closeout` |
| duplicate/oversell blocker | `blocked_p0_review_required` |
| missing D.4/D.5 fixture | warning, no crash |
| D.5 filled-good report | no execution authorization |
| CLI fixture read | no state writes |
| fake client write trap | no write methods called |

## Next Step

Use this report only as an operator decision summary. If it recommends `consider_reprice_decision`, the next step is still a separate approval-gated D.4/D.3 reprice decision prompt. Do not proceed to live cancel/replace, lifecycle apply, learning automation or parameter changes from this report.
