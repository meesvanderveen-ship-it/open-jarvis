# Post TP1 Fill Product Path Plan

Timestamp: `2026-05-29T18:25:00Z`

## Executive Recommendation

Use the existing D.45 trigger-aware operator cycle as the front door. If the active TP1 order produces `PARTIAL` or `FILLED` evidence, stop immediately and prepare `Controlled D.3 Lifecycle Apply on Fill Evidence v1` with a separate exact ACK. Do not auto-create TP2, auto-trail, auto-reprice, or change parameters from fill evidence.

Recommended next implementation task: **D.3 Post-TP1 Fill Apply Preview Pack v1**. It should produce an operator-facing, read-only preview that shows the exact state deltas for `PARTIAL` and `FILLED` before any ACK-gated apply can run.

## Current State Discovery Summary

Local state and current workflow docs agree that the active order is:

- ticker: `BTC-USDC`
- client_order_id: `phased4-BTCUSDC-TP1-repl-bc3330fe-20260529175801`
- exchange_order_id: `fd9f1d65-1623-4148-8bdd-c12ecf6d786d`
- linked_position_id: `76310097-849e-481c-b587-ba44bc3330fe`
- side: `SELL`
- label: `TP1`
- limit_price: `74000.00`
- size_base / remaining_size: `0.00006489`
- local status: `submitted`
- latest documented branch: `OPEN/open keep_open`
- fill_count: `0`
- filled_base / filled_quote: `0` / `0`
- reservation: `0.00006489`

Lineage:

- original `84800.00` TP1 was cancelled with zero fills
- D.4 controlled cancel-first replacement to `76000.00` succeeded
- D.4 controlled cancel-first replacement from `76000.00` to `74000.00` succeeded
- old `76000.00` and `84800.00` orders are not open

Position snapshot:

- `status=open`
- `bot_managed_base=0.0001297967431275`
- `position_size_base=0.0000649067431275`
- `reserved_base_open_exit_orders=0.00006489`
- `available_base_after_reservations` should remain the small residual around `0.0000000167431275` when computed from `position_size_base - reserved_base_open_exit_orders`
- `realized_pnl=0.130046532`
- `take_profit_price` is still historical/planning context and should not override the active D.4 replacement price

## Evidence Requirements

Lifecycle apply may only be considered after all evidence below is present:

- one fresh read-only Coinbase lifecycle/status snapshot for the active exchange order
- matching ticker, side `SELL`, client order id, exchange order id and linked position id
- raw status and normalized status are unambiguous
- fill summary is complete: `fill_count`, `filled_base`, `filled_quote`, `remaining_size`, average/actual fill price, fees and fill timestamps where available
- evidence hash is generated and shown to the operator
- local state before apply still matches the expected active order and reservation
- duplicate/oversell checks are false
- no other open exit exists for the same linked position
- filled amount is greater than zero for fill apply
- filled amount does not exceed the active order size or available bot-managed base
- exact future ACK for the controlled apply route is present

Missing, stale, mismatched, contradictory or overfilled evidence is a P0 fail-closed condition.

## PARTIAL Branch

If Coinbase evidence says `PARTIAL` with `filled_base > 0` and `remaining_size > 0`:

- stop the operator cycle
- do not cancel or replace the still-open remainder automatically
- prepare `Controlled D.3 Lifecycle Apply on Fill Evidence v1`
- preview the exact partial-fill deltas before apply
- apply only with a future exact ACK
- after ACK-gated apply, keep the order record open/submitted for the remaining open exchange order unless Coinbase later reports terminal status
- reduce local `position_size_base` and `bot_managed_base` by the filled base
- reduce `reserved_base_open_exit_orders` to the new remaining open order size
- recompute `available_base_after_reservations`
- increment/record fill count, filled base, filled quote, fees, actual fill price and evidence hash
- update realized PnL only for the filled slice; unrealized PnL remains for the still-open residual position
- keep D.2/D.3 plan state coherent as TP1 partially taken, not fully complete

Next action after partial apply: wait for the remaining order lifecycle, or run a separate decision-only route for the residual if a valid operator trigger exists.

## FILLED Branch

If Coinbase evidence says `FILLED` and `remaining_size=0`:

- stop the operator cycle
- prepare `Controlled D.3 Lifecycle Apply on Fill Evidence v1`
- preview exact full-fill deltas before apply
- apply only with a future exact ACK
- after ACK-gated apply, mark the open order record filled/closed locally
- set that order's `remaining_size` and reservation contribution to `0`
- reduce local `position_size_base` and `bot_managed_base` by the filled base
- set `reserved_base_open_exit_orders=0` for the filled TP1 order
- recompute `available_base_after_reservations`
- record filled base, filled quote, average/actual fill price, fees, fill count, evidence hash and final outcome
- update realized PnL for the filled TP1 slice
- leave unrealized PnL only for any remaining position base
- mark D.3 TP1 lifecycle complete
- keep D.4 reprice trail as historical; do not treat it as authorization for another order

If the fill consumes the entire managed position, the position may close only through the ACK-gated apply route after dust/min-notional checks. If a residual remains, keep it unmanaged by live automation until a separate runner/TP2/trailing decision is made.

## Filled But Local State Is Inconsistent

If evidence shows fill but local state has reservation drift, missing active order, duplicate exits, size mismatch, wrong order id, wrong position id, or impossible filled/remaining totals:

- fail closed
- do not apply lifecycle changes
- do not submit a replacement
- do not manually edit state
- produce a P0 drift report with evidence hash, expected state, actual state and proposed recovery route
- require a separate repair/reconcile task before any fill apply

The repair route should prefer fixture/temp-dir reproduction first, then an ACK-gated controlled recovery only if the drift cause is understood.

## Terminal No-Fill Branch

If evidence says `CANCELLED`, `EXPIRED` or `REJECTED` with zero fills:

- stop the operator cycle
- prepare `Controlled D.3 Terminal Closeout Reconcile v1`
- apply only with the terminal route's future exact ACK
- mark the order terminal locally and release its reservation only through that route
- leave the position base unchanged
- do not create a replacement automatically
- after terminal closeout, a separate operator decision may choose wait, new TP, D.4 reprice/new exit, or no exit

If terminal evidence includes any fill, route to fill lifecycle apply first or fail closed if the status/fill combination is not supported.

## OPEN/Open Branch

If evidence remains `OPEN/open` with zero fills:

- keep_open
- no lifecycle apply
- no local state mutation
- no cancel/replace
- no repeated monitoring unless a valid trigger exists
- optionally record a meaningful D.5 `open_no_fill_observation` only when the collection policy says the cycle is meaningful

## P0 Fail-Closed Conditions

Fail closed before any future apply if any condition is true:

- missing or wrong ACK
- no fresh read-only lifecycle evidence
- evidence hash mismatch
- wrong client order id or exchange order id
- wrong linked position id
- wrong side or ticker
- duplicate open exit
- oversell or filled_base greater than order size
- reservation mismatch not explained by the evidence
- local active order missing or already terminal
- unknown lifecycle status
- partial/fill totals do not reconcile
- Coinbase poll failure or uncertain status
- D.5 or learning output attempts to authorize execution

## Future ACK-Gated Apply Workflow

The future apply prompt should do this sequence:

1. Snapshot `state/open_orders.json` and `state/positions.json`.
2. Run local D.45/historical report for the active order.
3. Run exactly one read-only lifecycle poll if a valid lifecycle trigger exists.
4. Build fill or terminal evidence with a stable evidence hash.
5. Run preview-only D.3 apply/reconcile and show exact state deltas.
6. Verify P0 blockers are empty.
7. Require the route-specific exact ACK.
8. Apply once through the existing controlled route.
9. Run local post-check report and one read-only status check only if needed to confirm branch coherence.
10. Document the result and stop.

No live order action belongs inside fill apply. A later replacement, TP2 or trailing route must be a separate task.

## Remaining-Position Strategy After TP1

The preferred post-TP1 strategy is conservative:

- after `PARTIAL`: keep the exchange remainder open unless evidence or operator choice says otherwise
- after `FILLED`: do not immediately place TP2 or a stop order
- first reconcile the fill locally and compute the true residual base
- if residual notional is below minimum tradable size, classify it as dust/residual governance and do not force a sell
- if residual is tradable, run a separate decision-only remaining-position review
- candidate future routes are: wait with no open exit, create TP2, move/refresh invalidation, prepare a trailing-stop design, or wait for future D.4 dynamic trailing

Recommended default after a full TP1 fill: **reconcile first, then review residual separately**. Do not auto-run a runner strategy from the fill event.

## D.5 Learning-Log Events To Collect

Collect report-only events where available:

- `partial_fill_observation` for partial fills
- `filled_observation` for full fills
- `terminal_observation` for no-fill terminal statuses
- `open_no_fill_observation` for meaningful unchanged open cycles
- `safety_drift_observation` for mismatches or P0 blockers
- `operator_decision_observation` for ACK choices and post-fill strategic decisions

Fields should include order ids, lifecycle branch, planned exit price, actual fill price, current market mid if available, target distance, no-fill/stale duration, fill count, filled base/quote, remaining size, fees, slippage if available, reprice lineage, blockers, final outcome, `learning_to_execution_allowed=false` and `parameter_change_allowed=false`.

D.5 may inform a later Codex parameter review, but it must not authorize execution or parameter changes.

## Test Gaps And Implementation Tasks

Already covered:

- offline D.45/D.3 PARTIAL and FILLED routing
- terminal closeout routing for `CANCELLED`, `EXPIRED`, `REJECTED`
- P0 blockers fail closed
- D.5 report-only learning flags

Still useful before real fill apply:

- exact active-order post-TP1 fixture using `74000.00` replacement lineage
- preview report that renders state deltas for partial vs full fill without writing real state
- idempotency tests for repeated same evidence hash
- fee/PnL calculation fixtures for partial and full TP1 fills
- residual/dust classification tests after full TP1 fill
- mismatch tests for fill evidence on old `76000.00` or `84800.00` order ids
- D.5 learning-log event generation from the post-fill preview

## Recommended Next Codex Implementation Task

Task name: **D.3 Post-TP1 Fill Apply Preview Pack v1**

Scope:

- add fixture-only tests for active `74000.00` lineage partial/full fill previews
- add or extend a read-only preview helper only if existing reports cannot show exact deltas clearly
- prove no write occurs without exact ACK
- prove stale old-order fill evidence fails closed
- prove residual base, reservation release/reduction and realized PnL preview are coherent
- add D.5 learning-log fixture events for partial/full/terminal outcomes

Out of scope:

- real lifecycle apply
- live order action
- TP2 submit
- trailing stop automation
- parameter review

## Success Criteria

- Current active order is discovered from local state/docs, not assumed
- PARTIAL, FILLED, terminal and OPEN routes are explicit
- future apply requires exact ACK and evidence hash
- state deltas are described before any mutation
- remaining-position strategy is separate from fill reconciliation
- D.5 remains report-only
- no Coinbase write calls or trading-state writes occur in the planning task

## Validation Budget

For this docs-only plan:

- verify `docs/POST_TP1_FILL_PRODUCT_PATH_PLAN.md` exists
- no pytest required
- no Python compile required

For the recommended implementation task:

- focused post-fill preview tests
- D.3 lifecycle manager and terminal closeout tests
- D.45 exit operations and historical report tests
- D.5 learning-log tests
- compile changed Python files

## Stop Conditions

Stop immediately if:

- lifecycle evidence is `PARTIAL`, `FILLED`, `CANCELLED`, `EXPIRED` or `REJECTED`; route to the correct future ACK-gated workflow
- P0 drift appears
- evidence is uncertain
- a live action would be needed
- an apply would mutate real state
- learning output suggests execution or parameter changes

This plan does not authorize lifecycle apply, cancel, replace, submit, reprice, TP2, trailing automation, parameter review or learning automation.
