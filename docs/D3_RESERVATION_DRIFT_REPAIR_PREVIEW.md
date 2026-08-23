# D.3 Reservation Drift Repair Preview

## Purpose

This document defines the P0 reservation drift diagnosis and guarded repair-preview path for the active BTC-USDC D.3 TP1 SELL. The tool is preview-only by default and never calls Coinbase, never performs live action, never applies lifecycle changes, and never writes real trading state without a separate exact ACK.

Tool:

```bash
python3 tools/preview_or_apply_phase_d3_reservation_repair.py --json
```

## Diagnosis

Current real-state read-only values:

| Field | Value |
| --- | --- |
| ticker | `BTC-USDC` |
| client_order_id | `phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000` |
| exchange_order_id | `daa5ef77-9967-4fb0-b0c7-4f7c0680b512` |
| linked_position_id | `76310097-849e-481c-b587-ba44bc3330fe` |
| open D.3 exit count | `1` |
| local order status | `open` from local `submitted` |
| filled_base / fill_count | `0` / `0` |
| open_exit_remaining_size | `0.00006489` |
| position status | `open` |
| position_size_base | `0.0000649067431275` |
| bot_managed_base | `0.0001297967431275` |
| current reserved_base_open_exit_orders | `0` |

Root-cause hypothesis: prior D.3 local position recovery correctly established a reservation of `0.00006489`, but a later D.3 lifecycle/cancel-closeout/recovery path left or reset the local position reservation at `0` while a new active D.3 TP1 SELL remained open. The current blocker is therefore local reservation drift, not fill evidence and not terminal evidence.

## Invariant

If there is exactly one open D.3 SELL exit for the linked position and the order has zero fills:

- `reserved_base_open_exit_orders >= open_exit_remaining_size`
- `available_base_after_reservations_after >= 0`
- the position remains `open`
- duplicate open exits must be false
- oversell must be false

If the order is `PARTIAL` or `FILLED`, repair is blocked and the next route is D.3 lifecycle apply. If the order is `CANCELLED`, `EXPIRED` or `REJECTED`, repair is blocked and the next route is terminal closeout. If status is uncertain, no repair is allowed without lifecycle evidence.

## Preview Result

Real-state preview command run without `--apply`:

```bash
python3 tools/preview_or_apply_phase_d3_reservation_repair.py --json
```

Result:

- status: `d3_reservation_repair_preview_ready`
- blockers: `[]`
- warnings: `[]`
- current_reserved_base: `0`
- required_reserved_base: `0.00006489`
- proposed_reserved_base_after: `0.00006489`
- available_base_after_reservations_after: `0.0000649067431275`
- would_write_state: `false`
- apply_allowed: `false`
- no_coinbase_call: `true`
- no_live_action: `true`
- lifecycle_apply_performed: `false`
- state_write_performed: `false`

## Future Apply Gate

Exact ACK required:

```text
I_UNDERSTAND_AND_APPROVE_D3_RESERVATION_DRIFT_REPAIR_APPLY
```

Exact future apply command, not executed in this round:

```bash
python3 tools/preview_or_apply_phase_d3_reservation_repair.py \
  --apply \
  --repair-ack I_UNDERSTAND_AND_APPROVE_D3_RESERVATION_DRIFT_REPAIR_APPLY \
  --json
```

After any future guarded repair apply, the D.45 real-state operator report remains the checkpoint:

```bash
python3 tools/show_phase_d45_real_state_operator_report.py --json
```

Expected post-repair operator route, assuming no other drift appears, is `open_keep_open` and `wait_for_trigger`.

## Tests Run

Focused:

```bash
PYTHONPATH=. pytest -o cache_dir=/tmp/coinbase_bot_pytest_cache tests/test_phase_d3_reservation_repair_preview.py
```

Result: `10 passed`.

Combined:

```bash
PYTHONPATH=. pytest -o cache_dir=/tmp/coinbase_bot_pytest_cache \
  tests/test_phase_d45_real_state_operator_report.py \
  tests/test_phase_d45_operator_decision_report.py \
  tests/test_phase_d4_cancel_replace_planner.py \
  tests/test_phase_d4_trailing_preview.py \
  tests/test_phase_d5_execution_metrics.py \
  tests/test_phase_d3_reservation_repair_preview.py
```

Result: `70 passed`.

Compile:

```bash
python3 -m py_compile \
  bot/phase_d3_reservation_repair_preview.py \
  tools/preview_or_apply_phase_d3_reservation_repair.py \
  tools/show_phase_d45_real_state_operator_report.py
```

Result: passed.

## Next Product Step

Operator must decide whether to approve the exact guarded local reservation repair apply. Do not poll Coinbase, cancel/replace, lifecycle-apply, reprice, automate learning, or mutate parameters in the same step.
