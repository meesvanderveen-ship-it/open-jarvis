# D.3 Exit Lifecycle Test Strategy

Timestamp: `2026-05-29`

Scope: offline/fake/snapshot-based proof for the active D.3 exit lifecycle. This strategy explicitly excludes Coinbase submit, cancel, replace, service restarts, `.env` edits and real trading-state writes. Tests must use fake clients, supplied snapshots and `tmp_path` stores only.

Active lifecycle reference:
- ticker: `BTC-USDC`
- client order: `phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000`
- exchange order: `daa5ef77-9967-4fb0-b0c7-4f7c0680b512`
- size: `0.00006489`
- limit: `84800.00`
- latest branch: `OPEN/open keep_open`, zero fills
- operator decision: keep current TP1 / wait

## Test Method

Use three layers:

1. Snapshot classification tests for `bot.phase_d3_live_exit_reconciliation.reconcile_phase_d3_live_exit_order`.
   - Input: normalized Coinbase snapshot fixtures.
   - Stores: `OrderStore` and `StateStore` under `tmp_path`.
   - Required assertions: `no_coinbase_submit/cancel/replace`, no state write in dry-run, correct proposed order/position deltas, ACK-gated apply only in temp dirs.

2. Lifecycle orchestration tests for `bot.phase_d3_open_exit_lifecycle_manager.build_phase_d3_open_exit_lifecycle_report`.
   - Input: local-only preview, fake open snapshots, fake poll failure clients.
   - Required assertions: `OPEN/open` maps to `keep_open`, duplicate/oversell blocks, poll failure does not retry or apply.

3. Reprice/cancel-replace tests for `bot.phase_d3_cancel_replace_review` and `bot.phase_d3_cancel_replace_pilot`.
   - Input: fake `OPEN/open` snapshots and fake Coinbase clients.
   - Required assertions: review is dry-run, pilot preview performs no cancel/replace, armed pilot is ACK-gated, cancel failure prevents replace, duplicate/oversell blocks.

## Coverage Matrix

| Scenario | Expected branch | Existing coverage | Added/required scaffold | Safety assertion |
| --- | --- | --- | --- | --- |
| `OPEN/open keep_open` | keep open, no state write | `tests/test_phase_d3_live_exit_reconciliation.py::test_open_snapshot_dry_run_keeps_order_open`, `test_d3_open_keep_open_preserves_order_counts_and_position_snapshot`; `tests/test_phase_d3_open_exit_lifecycle_manager.py::test_preview_only_keeps_local_open_without_coinbase_poll`, `test_open_apply_is_noop_and_idempotent` | none | order counts and position unchanged; no Coinbase submit/cancel/replace |
| `PARTIAL` fill evidence | prepare/apply partial fill only with ACK | `test_partial_fill_dry_run_reduces_only_filled_delta`, `test_apply_partial_fill_updates_order_and_position`, `test_apply_is_idempotent_for_already_applied_partial`, `test_d3_partial_fill_multiple_deltas_preserve_remaining_reservation` | none | only fill delta reduces managed/reserved base; no new SELL |
| `FILLED` fill evidence | prepare/apply filled close of exit only with ACK | `test_full_fill_dry_run_releases_reservation_and_marks_tp1_complete`, `test_d3_filled_apply_revalidates_available_reserved_managed_base_semantics` | none | releases this reservation, never creates replacement SELL |
| `CANCELLED` terminal closeout | prepare/apply terminal closeout only with ACK | `test_cancelled_snapshot_dry_run_proposes_cancelled`, `test_d3_cancelled_closeout_requires_coherent_post_closeout_preview_state`; `tests/test_phase_d3_cancel_closeout_local_reconcile.py` | none | order terminal, reservation released, position remains open |
| `EXPIRED` terminal closeout | prepare/apply terminal closeout only with ACK | `test_expired_snapshot_dry_run_proposes_expired` | added `test_expired_apply_marks_terminal_without_position_size_change` | order terminal, reservation released, position size unchanged |
| `REJECTED` terminal closeout | prepare/apply terminal closeout only with ACK | `test_rejected_snapshot_dry_run_proposes_rejected`, `test_d3_rejected_branch_preserves_no_new_sell_before_closeout_complete`; `tests/test_phase_d3_rejected_submit_cleanup.py` | none | no fill deltas, no replacement, no retry |
| Poll failure | diagnostics only | `test_d3_unknown_network_failure_never_proposes_apply_or_trading_action`; `tests/test_phase_d3_open_exit_lifecycle_manager.py` fake failure clients; `tests/test_phase_d3_cancel_replace_pilot.py::test_poll_failure_diagnostics_are_exposed_without_live_action` | none | no retry storm, no apply, no cancel/replace |
| Reservation mismatch | block P0 safety | `tests/test_phase_d3_cancel_replace_review.py::test_oversell_reservation_mismatch_blocks_safety_review`, `tests/test_phase_d3_reservation_governance.py`, `tests/test_phase_d3_controlled_live_exits.py::test_d3_no_oversell_with_existing_reservation` | keep as regression suite | no second SELL and no oversell path |
| Duplicate/oversell guard | block P0 safety | `tests/test_phase_d3_open_exit_lifecycle_manager.py::test_blocks_duplicate_open_d3_orders_for_same_logical_position`, `tests/test_phase_d3_cancel_replace_review.py::test_duplicate_open_d3_exits_block_safety_review`, `tests/test_phase_d3_cancel_replace_pilot.py::test_duplicate_open_exit_before_replacement_blocks` | none | no live branch becomes ready with duplicate open exits |
| Reprice decision dry-run | review only, no cancel/replace | `tests/test_phase_d3_cancel_replace_review.py::test_coherent_coinbase_open_review_is_ready_for_future_pilot`, partial/filled/terminal route-away tests, poll failure test | none | candidate fields only; future ACK required |
| Cancel/replace dry-run without Coinbase write | preview ready, no cancel/replace, no state write | `tests/test_phase_d3_cancel_replace_pilot.py::test_preview_without_ack_is_ready` | strengthened with fake client assertions `client.cancelled == []`, `client.replaced == []` | no Coinbase write method called before ACK/live flags |

## Fixtures and Fakes

Recommended reusable fixture shape:
- `_snapshot(status, filled_base, filled_quote, avg_fill_price, fill_count, remaining_size)` for deterministic lifecycle evidence.
- fake clients with explicit write-method traps for dry-runs:
  - `cancel_order` records calls.
  - `place_limit_order` records calls.
  - submit methods raise `AssertionError` when a test must prove no live write.
- `tmp_path / state` and `tmp_path / logs` for every stateful test.

Avoid:
- default `OrderStore()` or `StateStore()` without `monkeypatch.chdir(tmp_path)` in tests.
- network clients unless the test is specifically a fake poll-failure diagnostic.
- any test that depends on BTC reaching `84800.00`.

## Targeted Pytest Set

Run this focused set after D.3 lifecycle changes:

```bash
pytest \
  tests/test_phase_d3_live_exit_reconciliation.py \
  tests/test_phase_d3_open_exit_lifecycle_manager.py \
  tests/test_phase_d3_cancel_closeout_local_reconcile.py \
  tests/test_phase_d3_cancel_replace_review.py \
  tests/test_phase_d3_cancel_replace_pilot.py \
  tests/test_phase_d3_reservation_governance.py \
  tests/test_phase_d3_controlled_live_exits.py
```

For a faster smoke run while editing:

```bash
pytest \
  tests/test_phase_d3_live_exit_reconciliation.py::test_d3_open_keep_open_preserves_order_counts_and_position_snapshot \
  tests/test_phase_d3_live_exit_reconciliation.py::test_expired_apply_marks_terminal_without_position_size_change \
  tests/test_phase_d3_cancel_replace_pilot.py::test_preview_without_ack_is_ready
```

## Remaining Gaps

- Terminal closeout helper `phase_d3_cancel_closeout_local_reconcile` is currently cancelled-specific. `EXPIRED` and `REJECTED` are covered by the generic D.3 reconciliation path, but a future helper generalization could make terminal closeout runbooks more uniform.
- Active-order fixture constants are duplicated across tests. A later small fixture module could reduce drift, but avoid broad refactor while the live order is open.
- Reprice choice documentation exists in runbooks, while executable reprice decision tests focus on cancel/replace review/pilot readiness. A future dry-run-only candidate builder could make option A/B/C testing more direct without touching live paths.

## Stop Condition

When the focused pytest set is green and this document is linked from `docs/CODEX_PROJECT_CONTEXT.md`, stop. Do not poll Coinbase, do not reprice, do not cancel/replace and do not update real trading state.
