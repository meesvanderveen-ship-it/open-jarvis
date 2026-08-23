# D.4 Dry-Run Cancel/Replace Planner

Timestamp: `2026-05-29`

## Purpose

This planner sits above the D.4 trailing preview scaffold. Given a `preview_reprice_candidate`, it prepares an exact future cancel-first replacement outline without calling Coinbase, cancelling, replacing, submitting, applying lifecycle evidence or writing trading state.

The planner is not a live executor. It only answers: if an operator later approves D.4 cancel/replace, what must happen first and what must still be blocked.

## Inputs

- D.4 trailing preview report
- current open D.3 exit order
- `linked_position_id`
- position snapshot with current reservation
- product rules, including `min_order_quote`
- open D.3 exit order list for duplicate detection
- optional fake Coinbase order status snapshot
- operator mode: `dry_run_only` or `future_ack_required`

## Outputs

- `status`
- `proposed_action`: `no_op_keep_open`, `dry_run_cancel_replace_plan_ready`, or `blocked`
- `current_order_id`
- `current_exchange_order_id`
- `current_price`
- `replacement_price`
- `replacement_size_base`
- `estimated_quote`
- `cancel_first_required=true`
- `replace_only_after_confirmed_cancel=true`
- `live_cancel_allowed=false`
- `live_replace_allowed=false`
- `no_coinbase_call=true`
- `no_live_action=true`
- `state_write_performed=false`
- `required_future_ack`
- `blockers`
- `warnings`
- `future_execution_outline`

## Safety Blockers

- preview is not `preview_reprice_candidate`
- no open D.3 exit order
- current order already has fills; route to D.3 lifecycle first
- duplicate open D.3 exits for the linked position
- reserved base is less than replacement size
- replacement candidate is below `min_order_quote`
- replacement candidate is post-only unsafe
- fake order status is `PARTIAL` or `FILLED`; route to D.3 fill lifecycle
- fake order status is `CANCELLED`, `EXPIRED`, or `REJECTED`; route to D.3 terminal closeout
- invalid operator mode

## Future ACK Requirements

When a dry-run plan is ready, the future executor would require:

- explicit operator choice to use the D.4 replacement candidate
- exact one-shot ACK: `I_UNDERSTAND_AND_APPROVE_D4_TRAILING_CANCEL_REPLACE_ONE_SHOT`
- confirmed cancel evidence before any replacement submit

This planner never treats the ACK as present. It only reports the required future ACK.

## Dry-Run Execution Outline

1. `cancel_existing_order`
   - dry-run only
   - live allowed now: false
   - requires future ACK
2. `wait_for_confirmed_cancel`
   - dry-run only
   - replacement remains forbidden
   - uncertain cancel fails closed
3. `submit_replacement_after_confirmed_cancel`
   - dry-run only
   - live allowed now: false
   - replacement requires confirmed cancel

## Test Matrix

| Scenario | Expected result |
| --- | --- |
| preview keep open | `no_op_keep_open`, no ACK required |
| preview candidate ready | dry-run plan ready, future ACK required |
| current order has fills | blocked, route to D.3 lifecycle |
| duplicate D.3 exits | P0 blocked |
| reservation mismatch | P0 oversell blocked |
| replacement below min quote | blocked |
| replacement post-only unsafe | blocked |
| fake terminal status | blocked, terminal closeout route |
| fake partial/filled status | blocked, fill lifecycle route |
| cancel-first sequencing | cancel step precedes replacement step |
| fake client write traps | no write methods called |
| CLI fixture read | no state file writes |

## Next Step

Keep this planner dry-run only. Do not wire it to live cancel/replace while the active D.3 TP1 remains `OPEN/open keep_open`. A future live D.4 executor would need a separate approval, confirmed cancel evidence, exact replacement price and one-shot ACK.
