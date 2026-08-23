# D.45 Lifecycle Simulation Hardening v1

## Scope

This hardening pass proves the D.45 -> D.3 lifecycle handoff with fixture-only tests while the active BTC-USDC TP1 replacement order remains untouched at `76000.00`.

It does not call Coinbase, submit, cancel, replace, reprice, lifecycle-apply real state, write real trading state, restart services or enable learning-to-execution.

## Simulation Matrix

| Fixture evidence | D.45 route | D.3 behavior | Apply gate |
| --- | --- | --- | --- |
| `OPEN/open`, zero fills | `open_keep_open` / `keep_open` | mutation-free keep-open branch | no ACK needed because no apply |
| `PARTIAL` with nonzero fill | `fill_evidence` -> `Controlled D.3 Lifecycle Apply on Fill Evidence v1` | preview is read-only; temp apply can update only temp stores | `I_UNDERSTAND_AND_APPROVE_D3_OPEN_EXIT_LIFECYCLE_APPLY` |
| `FILLED` with full fill | `fill_evidence` -> `Controlled D.3 Lifecycle Apply on Fill Evidence v1` | preview is read-only; temp apply finalizes only temp order/state and repeat apply is idempotent | `I_UNDERSTAND_AND_APPROVE_D3_OPEN_EXIT_LIFECYCLE_APPLY` |
| `CANCELLED` | `terminal_evidence` -> `Controlled D.3 Terminal Closeout Reconcile v1` | preview is read-only; closeout helper remains ACK/hash gated | `I_UNDERSTAND_AND_APPROVE_D3_CANCEL_CLOSEOUT_LOCAL_RECONCILE` for local closeout helper |
| `EXPIRED` / `REJECTED` | `terminal_evidence` -> `Controlled D.3 Terminal Closeout Reconcile v1` | generic D.3 lifecycle preview is read-only; temp apply remains ACK gated | `I_UNDERSTAND_AND_APPROVE_D3_OPEN_EXIT_LIFECYCLE_APPLY` |
| unknown status | fail closed | no apply | none |
| duplicate exit, reservation mismatch or oversell | P0 block | no route proceeds to apply | none |

## Tests

Added `tests/test_phase_d45_lifecycle_simulation_hardening.py`.

The tests use `tmp_path` stores and fixture payloads only. They assert:

- D.45 reports never submit, cancel, replace or write state.
- fill and terminal evidence route to the correct next controlled workflow.
- missing/wrong ACK blocks apply.
- evidence hash mismatch blocks cancelled closeout.
- terminal status with fill evidence fails closed.
- OPEN/open zero-fill remains `keep_open`.
- P0 duplicate/reservation blockers fail closed before lifecycle routing.
- D.5 enrichment remains `report_only` with `learning_to_execution_allowed=false`.

## Future Boundaries

Real fill or terminal evidence still requires a separate operator workflow and exact ACK. This hardening pass does not arm, consume or imply any ACK.

Do not use these fixture tests as permission for live monitoring, live reprice, cancel/replace, live lifecycle apply, split-exit architecture, micro-position testing or learning automation.

