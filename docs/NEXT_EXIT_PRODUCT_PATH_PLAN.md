# Next Exit Product Path Plan

## Executive Recommendation

Recommended path: **bundle B + C, with light D framing**.

Build one offline, fixture-driven lifecycle simulation hardening task next:

- PARTIAL and FILLED lifecycle simulation coverage through the existing D.45 -> D.3 fill-apply route.
- CANCELLED, EXPIRED and REJECTED terminal closeout simulation coverage through the existing D.45 -> D.3 terminal route.
- Operator-cycle output checks that prove the next route is explicit, ACK-gated and mutation-free until a later approved apply.
- A small decision-only reprice framework note for a future `74500-75000` review, without implementing execution, changing parameters or touching the live order.

Do not touch the active `76000.00` order. Do not poll Coinbase just to confirm another identical `OPEN/open`. Do not run another reprice route until a new decision-only report and ACK exist.

## Current State Summary

Active live order:

| Field | Value |
| --- | --- |
| ticker | `BTC-USDC` |
| client_order_id | `phased4-BTCUSDC-TP1-repl-bc3330fe-20260529064443` |
| exchange_order_id | `6f6fa436-f5b9-4df5-bb23-ddf35a27a56a` |
| linked_position_id | `76310097-849e-481c-b587-ba44bc3330fe` |
| limit_price | `76000.00` |
| size_base / remaining_size | `0.00006489` |
| latest known status | `OPEN/open` |
| fills | `0` |
| reservation | `0.00006489` |

The old `84800.00` order is cancelled with zero fills. D.4 controlled cancel-first replacement to `76000.00` succeeded. D.45 historical reporting, D.45 exit operations hardening, D.5 no-fill/stale metrics and the D.4 stale fixture regression fix already exist.

The latest strategy decision said `76000.00` was `far_from_target`, D.5 was `consider_reprice_later`, and the selected operating stance was `G + E`: keep `76000.00` for a bounded `4-6 hour` window, run offline lifecycle/fill testing separately, and only consider another future reprice after a fresh decision-only report and ACK.

## Candidate Paths

| Path | Product value | Safety risk | Implementation effort | Tests needed | Live/state risk | Recommended priority |
| --- | --- | --- | --- | --- | --- | --- |
| A. Wait only | Low by itself; preserves safety while market develops | Very low | None | None | None | Medium as operating posture, not product work |
| B. Offline lifecycle/fill simulation hardening | High; proves PARTIAL/FILLED route before real evidence appears | Low if temp dirs/fixtures only | Medium | D.45 fill route, D.3 preview/apply-gate, idempotency, no-write assertions | None if no real state | **P1** |
| C. Terminal closeout simulation hardening | High; proves CANCELLED/EXPIRED/REJECTED closeout route | Low if temp dirs/fixtures only | Medium | terminal route, reservation-release preview, ACK block, no-write assertions | None if no real state | **P1** |
| D. Future reprice decision framework | Medium; prepares a cleaner `74500-75000` later decision | Low if docs/report-only | Low/medium | Decision-only fixtures; no execution assertions | None if report-only | P2, include lightly |
| E. Split-style partial exit design | Medium later; could improve de-risking flexibility | Medium/high now due partial reservations and duplicate/oversell risk | High | reservation partition, multi-order invariants, fill allocation, cancel/replace gates | Future live risk if rushed | Later |
| F. Micro-position future live test | Medium later; tests real exchange lifecycle on tiny size | Medium due real orders and reservation interaction | High | full live gate, isolated position, rollback/closeout | Real live/state risk | Later only |

## Planning Answers

1. Best next product path while `76000.00` waits: build offline lifecycle/fill plus terminal simulation hardening. It advances readiness for the next real lifecycle event without monitoring churn or live-order changes.
2. PARTIAL/FILLED lifecycle simulation should be first because it protects the highest-risk profitable/fill path: evidence capture, route selection, ACK gate and no accidental double-apply.
3. Terminal closeout simulation should be bundled with it because it uses adjacent fixtures and proves reservation release behavior for cancel/expire/reject evidence.
4. Improve next operator cycle tooling only where it supports those simulations: clear route labels, required ACKs, no-write flags and fixture CLI smoke checks. Avoid a broad UX/tooling refactor.
5. Prepare only a future reprice decision framework for `74500-75000`: define comparison inputs and stop rules, but do not execute, arm ACKs, change parameters or generate an automatic recommendation from D.5.
6. Split-style partial exit architecture is not worth implementing now. Capture it as a later design because partial reservations and multi-exit accounting are P0-sensitive.
7. Safe bundle for one next Codex task: "Offline D.3/D.45 Lifecycle Simulation Hardening v1" covering B + C plus a small D decision-only appendix.
8. Explicitly do not do: Coinbase poll/write, cancel/replace/submit/reprice, lifecycle apply on real state, trading-state write, service restart, `.env` mutation, learning-to-execution, split live architecture or micro-position live test.

## Recommended Next Implementation Task

Task name: **Offline D.3/D.45 Lifecycle Simulation Hardening v1**.

Scope:

- Add or extend fixture-only tests for D.45 exit operations report routes:
  - `PARTIAL` with nonzero fill -> `Controlled D.3 Lifecycle Apply on Fill Evidence v1`.
  - `FILLED` with full fill -> same fill-apply route.
  - `CANCELLED`, `EXPIRED`, `REJECTED` -> `Controlled D.3 Terminal Closeout Reconcile v1`.
- Add or extend D.3 lifecycle manager tests that prove preview/apply behavior is ACK-gated and idempotent for fake PARTIAL/FILLED evidence.
- Add or extend terminal closeout tests that prove preview is read-only, wrong/missing ACK blocks, evidence hash mismatch blocks, and apply behavior is tested only in temp state.
- Add a fixture CLI smoke test if current CLI coverage is missing for the combined D.45 -> route handoff.
- Add a short docs update summarizing the simulation matrix and future ACK boundaries.

Do not include live monitoring or live preflight. Do not use current real state except as read-only reference for field names.

## Acceptance Criteria

- All new tests use temp dirs, fixture payloads or in-memory stores.
- Tests assert no Coinbase submit/cancel/replace/write path is called.
- Tests assert no real `state/open_orders.json`, `state/positions.json` or `.env` mutation.
- PARTIAL and FILLED evidence route to fill lifecycle apply, but do not apply without the explicit D.3 ACK.
- Terminal evidence routes to terminal closeout, but does not reconcile/apply without the explicit ACK.
- Existing `OPEN/open` zero-fill behavior remains `keep_open` and mutation-free.
- Duplicate/oversell/reservation mismatch still fail closed before any route that could apply.
- D.5 remains report-only and `learning_to_execution_allowed=false`.
- Documentation names the future ACKs and stop conditions.

## Suggested Validation Budget

Run focused tests first:

```bash
pytest tests/test_phase_d45_exit_operations_report.py tests/test_phase_d3_open_exit_lifecycle_manager.py tests/test_phase_d3_cancel_closeout_local_reconcile.py
```

If code changes touch shared D.3/D.4/D.5/D45 modules, run the broader relevant regression:

```bash
pytest tests/test_phase_d3_open_exit_lifecycle_manager.py tests/test_phase_d3_cancel_closeout_local_reconcile.py tests/test_phase_d45_exit_operations_report.py tests/test_phase_d45_historical_exit_operations_report.py tests/test_phase_d5_execution_metrics.py tests/test_phase_d45_operator_decision_report.py
```

Compile changed Python files only:

```bash
python3 -m py_compile <changed-python-files>
```

For this planning pass, no pytest is required because only docs are changed.

## Required Docs Updates

For the next implementation task:

- Add a concise lifecycle simulation hardening doc, or extend `docs/D45_EXIT_OPERATIONS_HARDENING.md`.
- Update `docs/CODEX_PROJECT_CONTEXT.md` with one checkpoint after tests pass.
- Optionally add a prompt template for `Offline D.3/D.45 Lifecycle Simulation Hardening v1`.

This planning pass creates `docs/NEXT_EXIT_PRODUCT_PATH_PLAN.md` and adds only a short context checkpoint.

## Stop Conditions

Stop immediately if:

- a task would require Coinbase write access, cancel/replace/submit/reprice or service restart;
- a workflow needs real lifecycle apply or terminal closeout apply on real state;
- local state drift, duplicate-open exits, oversell or reservation mismatch appears;
- the active order has real PARTIAL/FILLED/terminal evidence, which requires a separate ACK-gated workflow;
- the plan-only task is complete.

If there is no live trigger and no approved implementation task: `wachten tot trigger`.

## Future ACKs

Future D.3 fill/terminal apply requires a separate prompt, real evidence and ACK:

```text
I_UNDERSTAND_AND_APPROVE_D3_OPEN_EXIT_LIFECYCLE_APPLY
```

Any future controlled cancel/replace reprice requires a fresh decision-only report, exact target, full preflight and ACK:

```text
I_UNDERSTAND_AND_APPROVE_D4_TRAILING_CANCEL_REPLACE_ONE_SHOT
```

No ACK is armed, consumed or implied by this plan.

