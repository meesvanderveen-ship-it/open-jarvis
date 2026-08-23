# D.45 Real-State Read-Only Operator Report

## Purpose

`tools/show_phase_d45_real_state_operator_report.py` builds one local-only D.45 operator report from real state files. It reads D.3 order evidence, derives a local lifecycle event, attaches a no-market D.4 preview warning, builds D.5 metrics, and routes the result through the existing D.45 operator decision layer.

This report is read-only/report-only. It never polls Coinbase, never cancels, never replaces, never submits, never applies lifecycle changes, and never writes trading state.

## Read-Only Local-State Inputs

- `state/open_orders.json`
- `state/positions.json`
- ticker, client order id and exchange order id
- optional operator mode: `wait_only`, `decision_only`, `future_reprice_consideration`

The current active D.3 TP1 SELL lookup defaults to:

- ticker: `BTC-USDC`
- client_order_id: `phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000`
- exchange_order_id: `daa5ef77-9967-4fb0-b0c7-4f7c0680b512`

## Expected Current Active-Order Result

For a consistent local `OPEN/open` or `submitted/open` zero-fill state with matching reservation, the expected recommendation is:

- `lifecycle_branch=open_keep_open`
- `recommended_operator_action=wait_for_trigger`
- `d5_metrics_summary.fill_quality_label=no_fill_open`
- `no_coinbase_call=true`
- `no_live_action=true`
- `state_write_performed=false`
- `learning_to_execution_allowed=false`

If local state has reservation drift, duplicate exits, missing order evidence or another P0 condition, the report must block instead of correcting state.

## Safety Branches

| Evidence | Recommended route |
| --- | --- |
| Active order missing | `blocked_p0_review_required` |
| Duplicate open D.3 exits for same position | `blocked_p0_review_required` |
| `reserved_base_open_exit_orders < remaining_size` | `blocked_p0_review_required` |
| `OPEN/open` zero fill, no D.4 candidate | `wait_for_trigger` |
| `PARTIAL/FILLED` or non-zero fills | `prepare_fill_lifecycle_apply` |
| `CANCELLED/EXPIRED/REJECTED` | `prepare_terminal_closeout` |

The D.4 preview is local-only when no market snapshot is supplied and emits `market_snapshot_missing_local_only`. That warning cannot authorize cancel/replace.

## Test Matrix

| Scenario | Expected |
| --- | --- |
| Active order `OPEN/no-fill` with matching reservation | `wait_for_trigger` |
| `PARTIAL` or `FILLED` evidence | `prepare_fill_lifecycle_apply` |
| `CANCELLED`, `EXPIRED` or `REJECTED` evidence | `prepare_terminal_closeout` |
| Target order missing | P0 blocked |
| Duplicate open D.3 exits | P0 blocked |
| Reservation mismatch | P0 blocked |
| CLI fixture read | no state file writes |

## Next Step

Use this report as the operator read-only checkpoint before any future D.3 lifecycle apply or D.4 reprice consideration. Any fill apply, terminal closeout or cancel/replace still requires a separate exact operator approval and ACK.
