# Codex Workflow for Coinbase Spot LLM Tradingbot

## 1. Purpose

Work productively on the Coinbase spot LLM tradingbot without breaking safety. Codex should take one clear safe product step when available, and stop when approval, safety or lifecycle evidence requires a separate operator ACK.

## 2. Current lifecycle state

Latest D.4/D.3 TP1 SELL:

- ticker: `BTC-USDC`
- client_order_id: `phased4-BTCUSDC-TP1-repl-bc3330fe-20260529175801`
- exchange_order_id/order_id: `fd9f1d65-1623-4148-8bdd-c12ecf6d786d`
- linked_position_id: `76310097-849e-481c-b587-ba44bc3330fe`
- side: `SELL`
- label: `TP1`
- size_base: `0.00006489`
- remaining_size: `0`
- limit_price: `74000.00`
- post_only: `true`
- reduce_only_local: `true`
- local status: `filled`
- latest Coinbase status: `FILLED/filled`
- filled_base: `0.00006489`
- filled_quote: `4.80186000`
- avg_fill_price: `74000`
- fees_paid: `0.02881116`
- fill_count: `1`
- proposed_action: none; lifecycle apply already completed

Latest D.3 TP_CLOSE residual SELL:

- ticker: `BTC-USDC`
- client_order_id: `phased3-BTCUSDC-TPCLOSE-repl-pos1-20260530215029`
- exchange_order_id/order_id: `8bcafe10-d31c-4067-886d-324d0f284967`
- linked_position_id: `pos-1`
- side: `SELL`
- label: `TP_CLOSE`
- size_base: `0.00006490`
- remaining_size: `0`
- limit_price: `74000.00`
- local status: `filled`
- latest Coinbase status: `FILLED/filled`
- filled_base: `0.0000649`
- filled_quote: `4.8026000`
- avg_fill_price: `74000`
- fill_count: `1`
- direct Coinbase fee evidence: `0.0288156`
- lifecycle persisted fees: `0`
- proposed_action: none; lifecycle apply already completed

Local state:

- position status: `closed`
- position_size_base: `0`
- bot_managed_base: `0`
- dust classification: no current manageable BTC-USDC position; earlier practical dust has been locally zeroed/closed without authorizing any new trade
- open_orders: `0`
- open D.3 exit count: `0`
- derived reserved_base_open_exit_orders: `0`
- stale denormalized position field: `state/positions.json` still has `reserved_base_open_exit_orders=0.00006490`
- duplicate/oversell: `false/false`
- auditstatus: `ok_observe_only`
- warning: the generic open-exit reservation repair preview returned `d3_reservation_repair_blocked` / `suggested_action=no_apply`; do not use it blindly for post-filled stale-field cleanup
- environment warning: `bwrap` is missing on PATH on Ubuntu 24.04.4; Codex may use bundled bubblewrap fallback. Install only in a separate approved maintenance task.

Current operator boundary:

- no active D.3 exit order is pending
- no lifecycle apply, local repair apply, dust-close trade, manual position close, new TP2, runner, trailing, re-entry, cancel/replace/reprice or additional live order without a separate exact ACK
- D.6 research may resume only as a separate report-only task unless explicitly approved

## 3. Priority model

- P0: no duplicate/oversell, no second SELL, no unauthorized live action, no unauthorized state write, no retry-storm, no manual state edit.
- P1: active D.3 exit lifecycle monitoring, correct fill evidence apply with ACK, correct terminal evidence reconcile with ACK, reprice only with explicit choice and ACK.
- P2: workflow/documentation improvement, sandbox DNS/host-shell limit management, prompt template maintenance, monitor-only warning tracking.
- P3: D.4 trailing/cancel-replace automation, D.5 execution learning, follower/replication and further strategy improvement.

## 4. Standard task loop

1. Read context via targeted `rg` and recent `tail`, not full-doc scanning by default.
2. Run state/sanity checks only when needed for the task and only read-only unless approved.
3. Classify the next work under P0/P1/P2/P3.
4. Take one safe product step.
5. Stop at the defined stop condition.
6. Update docs only for a real checkpoint.
7. Return a short final report.

## 5. Monitor trigger policy

There is currently no open TP_CLOSE order to monitor. If a future active lifecycle order is approved and observed as `OPEN/open` with zero fills, that branch means `keep_open`. This is the no monitor-loop rule.

Do not run a new Coinbase lifecycle poll unless at least one trigger is true:

- future approved active lifecycle trigger: a new active order exists and the operator wants current status
- lifecycle trigger: UI/logs/alerts suggest fill, partial, cancel, reject, expiry or status change
- safety trigger: local drift, reservation mismatch, duplicate/oversell or service/runtime issue
- explicit operator request

If no trigger exists:

- no Coinbase poll
- no live action
- no state write
- stop with: `wachten tot trigger`

## 6. D.3 lifecycle branches

OPEN/open:

- `keep_open`
- no state write
- no live action
- stop until trigger

PARTIAL/FILLED:

- stop
- prepare `Controlled D.3 Lifecycle Apply on Fill Evidence v1`
- separate ACK required before apply

CANCELLED/EXPIRED/REJECTED:

- stop
- prepare `Controlled D.3 Terminal Closeout Reconcile v1`
- separate ACK required before reconcile/apply

Poll failure:

- no retry-storm
- diagnostics only
- fix lookup/connectivity before any further lifecycle decision

## 7. Reprice policy

A keep current `84800.00`:

- no action
- no cancel
- no replacement

B near-market de-risk:

- only with explicit loss/de-risk approval
- cancel-first
- replacement only after confirmed cancel
- exact one-shot ACK required

C plan-preserving `82000.00`:

- only with explicit approval
- cancel-first
- replacement only after confirmed cancel
- exact one-shot ACK required

## 8. Docs policy

Update docs for:

- live submit
- cancel/replace
- fill apply
- terminal closeout
- safety incident
- workflow change
- reprice decision
- new active lifecycle order

Do not expand docs for:

- identical `OPEN/open keep_open` monitor with no new information
- ordinary sanity check without status change
- repeated price check without a decision

## 9. Stop conditions

Stop immediately when:

- approval or ACK is missing for a live action or state mutation
- P0 safety gate fails
- lifecycle evidence is `PARTIAL`, `FILLED`, `CANCELLED`, `EXPIRED` or `REJECTED`
- poll/connectivity fails and diagnostics are complete
- no monitor trigger exists
- one safe product step is complete

## 10. Final report format

Every round ends with:

- uitgevoerde taak
- status/resultaat
- gewijzigde bestanden
- tests/checks
- P0/P1/P2/P3 update
- volgende productstap
- expliciete stopconditie als er niets meer moet gebeuren
