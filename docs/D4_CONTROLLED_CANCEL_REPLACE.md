# D.4 Controlled Cancel/Replace

## Purpose

This checkpoint documents the guarded D.4 controlled cancel/replace attempt for the active BTC-USDC D.3 TP1 SELL. The operator selected target replacement price `76000.00` and provided `I_UNDERSTAND_AND_APPROVE_D4_TRAILING_CANCEL_REPLACE_ONE_SHOT`.

The route is cancel-first and fail-closed. Replacement must never be submitted before confirmed cancel evidence and a green replacement submit gate.

## Preflight Values

Backups:

- `/tmp/coinbase_bot_d4_cancel_replace_20260529_0618/open_orders.before.json`
- `/tmp/coinbase_bot_d4_cancel_replace_20260529_0618/positions.before.json`

Current order:

| Field | Value |
| --- | --- |
| ticker | `BTC-USDC` |
| client_order_id | `phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000` |
| exchange_order_id | `daa5ef77-9967-4fb0-b0c7-4f7c0680b512` |
| linked_position_id | `76310097-849e-481c-b587-ba44bc3330fe` |
| current limit | `84800.00` |
| target replacement limit | `76000.00` |
| remaining_size | `0.00006489` |
| reservation | `0.00006489` |

Local D.45 preflight:

- `order_found=true`
- `lifecycle_branch=open_keep_open`
- `reserved_base_open_exit_orders=0.00006489`
- `fill_count=0`
- `blockers=[]`
- `recommended_operator_action=wait_for_trigger`

Read-only lifecycle poll:

- Coinbase raw status: `OPEN`
- normalized status: `open`
- filled_base: `0`
- fill_count: `0`
- remaining_size: `0.00006489`
- suggested_action: `keep_open`
- no local state write

## Market Snapshot

Read-only Coinbase product-book:

- best_bid: `73693.64`
- best_ask: `73693.65`
- mid_price: `73693.645`
- time: `2026-05-29T06:22:19.371517Z`
- source: `/api/v3/brokerage/market/product_book`
- auth_required: `false`

Product rules:

- base_increment: `0.00000001`
- price_increment: `0.01`
- min_order_quote: `1`
- min_order_base: `0.00000001`

Target validation:

- `76000.00 > best_ask`, post-only SELL feasible at preflight snapshot
- estimated_quote: `4.9316400000`
- estimated_quote >= min_order_quote
- size respects base_increment
- price respects price_increment
- reservation >= replacement size
- duplicate/oversell false

## Dry-Run Planner

D.4 dry-run planner result:

- status: `d4_cancel_replace_plan_ready`
- proposed_action: `dry_run_cancel_replace_plan_ready`
- replacement_price: `76000.00`
- replacement_size_base: `0.00006489`
- estimated_quote: `4.9316400000`
- cancel_first_required: `true`
- replace_only_after_confirmed_cancel: `true`
- required_future_ack: `I_UNDERSTAND_AND_APPROVE_D4_TRAILING_CANCEL_REPLACE_ONE_SHOT`
- blockers: `[]`

## Live Gate Result

Execution stopped before cancel.

Reason: replacement submit was not green under the central live-exit gate. Current runtime flags keep live exits disabled and `phase_d4_controlled_cancel_replace` is not an explicitly allowed live SELL source.

Blocking live-exit gate reasons:

- `enable_live_exit_orders_false`
- `autonomous_allow_exits_false`
- `enable_phase_d3_actual_exit_submit_false`
- `phase_c_disable_exit_limit_orders_true`
- `source_not_explicitly_allowed_for_live_sell`

Because replacement could not be guaranteed after cancel, the route failed closed before the cancel attempt.

## Replacement Submit Gate Integration

D.4 Controlled Replacement Submit Gate v1 adds a narrow central-gate evaluator for source:

- `phase_d4_controlled_cancel_replace`

This source is not a general live-exit release. It can become green only when a future runner provides:

- exact ACK `I_UNDERSTAND_AND_APPROVE_D4_TRAILING_CANCEL_REPLACE_ONE_SHOT`
- process-local one-shot arming
- confirmed cancel evidence for the old order before replacement submit
- one scoped SELL replacement candidate with `post_only=true` and `reduce_only_local=true`
- coherent reservation, no duplicate exit, no oversell, and valid product rules

Default safety flags remain blocked and `.env` is not mutated. See `docs/D4_CONTROLLED_REPLACEMENT_SUBMIT_GATE.md`.

## Results

- cancel attempt executed: `no`
- confirmed cancel evidence: `not applicable`
- replacement submit executed: `no`
- new client_order_id: `not created`
- new exchange_order_id: `not created`
- lifecycle apply: `no`
- trading-state write: `no`

Post-stop D.45 result:

- `lifecycle_branch=open_keep_open`
- `recommended_operator_action=wait_for_trigger`
- `reserved_base_open_exit_orders=0.00006489`
- `open_d3_exit_count_for_position=1`
- `blockers=[]`

`state/open_orders.json` and `state/positions.json` remained byte-identical to their preflight snapshots.

## Tests

Combined D.3/D.4/D.5/D45 pytest:

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

## Next Step

Do not cancel the current order until the replacement submit path has a green, explicitly approved live-exit gate. The current TP1 remains open at `84800.00`.

## Retry Result: Controlled Reprice to 76000.00

Timestamp: `2026-05-29T06:45:00Z`

Outcome: `d4_controlled_cancel_replace_applied`.

Preflight:

- local D.45: `open_keep_open`, zero fills, reservation `0.00006489`, blockers `[]`
- read-only lifecycle before cancel: old order `OPEN/open`, zero fills, remaining `0.00006489`
- market snapshot before live route: best bid/ask about `73592.00/73592.01`
- replacement target: `76000.00`
- estimated quote: `4.9316400000`
- product rules: base increment `0.00000001`, price increment `0.01`, min quote `1`
- D.4 dry-run planner: `d4_cancel_replace_plan_ready`
- replacement gate before cancel: blocked only by `d4_replacement_confirmed_cancel_required`
- replacement gate after confirmed cancel: `allowed=true`

Live route:

- cancel calls: `1`
- old order id: `daa5ef77-9967-4fb0-b0c7-4f7c0680b512`
- Coinbase cancel response shape: `results[0].success=true`; runner initially failed closed before replacement because that response shape was not recognized as confirmed
- follow-up read-only Coinbase evidence confirmed old order `CANCELLED`, zero fills
- resume path executed with no second cancel
- replacement submit calls: `1`
- new client order id: `phased4-BTCUSDC-TP1-repl-bc3330fe-20260529064443`
- new exchange order id: `6f6fa436-f5b9-4df5-bb23-ddf35a27a56a`
- new limit price: `76000.00`
- new size: `0.00006489`
- post-only: `true`
- reduce-only local: `true`

Post-check:

- read-only Coinbase replacement status: `OPEN/open`, zero fills, remaining `0.00006489`
- local D.45 for new order: `lifecycle_branch=open_keep_open`, `recommended_operator_action=wait_for_trigger`, blockers `[]`
- local open exits: exactly `1`
- old order local status: `cancelled`
- new order local status: `submitted`
- reservation: `0.00006489`
- duplicate/oversell: `false/false`
- lifecycle apply: `no`
- service restart: `no`
- `.env` mutation: `no`

Validation:

```bash
PYTHONPATH=. pytest -o cache_dir=/tmp/coinbase_bot_pytest_cache \
  tests/test_phase_d45_real_state_operator_report.py \
  tests/test_phase_d45_operator_decision_report.py \
  tests/test_phase_d4_cancel_replace_planner.py \
  tests/test_phase_d4_trailing_preview.py \
  tests/test_phase_d5_execution_metrics.py \
  tests/test_phase_d3_reservation_repair_preview.py \
  tests/test_live_exit_gate_d4_controlled_cancel_replace.py \
  tests/test_phase_d4_controlled_cancel_replace.py
```

Result: `92 passed`.

Compile validation:

```bash
python3 -m py_compile \
  bot/live_exit_gate.py \
  bot/phase_d4_controlled_cancel_replace.py \
  tools/run_phase_d4_controlled_cancel_replace.py
```

Result: passed.

Next step:

Wait for a lifecycle trigger on the new TP1 replacement order at `76000.00`. Do not run another reprice, cancel/replace, lifecycle apply or learning automation without a new explicit prompt and ACK.

## Retry Result: Controlled Reprice to 74000.00

Timestamp: `2026-05-29T18:05:00Z`

Outcome: `d4_controlled_cancel_replace_applied`.

Preflight:

- backups: `/tmp/coinbase_bot_d4_74000_20260529_01/open_orders.before.json` and `/tmp/coinbase_bot_d4_74000_20260529_01/positions.before.json`
- local D.45/historical: active `76000.00` order `phased4-BTCUSDC-TP1-repl-bc3330fe-20260529064443` / `6f6fa436-f5b9-4df5-bb23-ddf35a27a56a`, `OPEN/open`, zero fills, remaining/reservation `0.00006489`, exactly one open exit, blockers `[]`
- old `84800.00` order: not open, zero fills
- read-only lifecycle before cancel: old `76000.00` order `OPEN/open`, zero fills, remaining `0.00006489`
- market snapshot before live route: best bid/ask `73820.06/73821.99`
- replacement target: `74000.00`
- estimated quote: `4.8018600000`
- product rules: base increment `0.00000001`, price increment `0.01`, min quote `1`
- post-only validation: `74000.00 > best_ask`, so the SELL was post-only safe at preflight
- D.4 dry-run planner: `d4_cancel_replace_plan_ready`
- replacement gate before cancel: blocked only by `d4_replacement_confirmed_cancel_required`
- replacement gate after simulated confirmed cancel: `allowed=true`

Live route:

- cancel calls: `1`
- old order id: `6f6fa436-f5b9-4df5-bb23-ddf35a27a56a`
- cancel response: `results[0].success=true`
- post-cancel evidence: `CANCELLED`, zero fills, remaining `0.00006489`
- local old-order closeout: old `76000.00` order marked `cancelled`, reservation retained for replacement
- lifecycle apply: `no`
- replacement submit calls: `1`
- new client order id: `phased4-BTCUSDC-TP1-repl-bc3330fe-20260529175801`
- new exchange order id: `fd9f1d65-1623-4148-8bdd-c12ecf6d786d`
- new limit price: `74000.00`
- new size: `0.00006489`
- post-only: `true`
- reduce-only local: `true`

Post-check:

- read-only Coinbase replacement status: `OPEN/open`, zero fills, remaining `0.00006489`
- post-submit book snapshot: best bid/ask `73860.01/73860.02`; target remained post-only safe
- local D.45/historical for new order: `lifecycle_branch=open_keep_open`, `recommended_operator_action=wait_for_trigger`, blockers `[]`
- local open exits: exactly `1`
- old `76000.00` order local status: `cancelled`
- old `84800.00` order: not open
- new order local status: `submitted`
- reservation: `0.00006489`
- duplicate/oversell: `false/false`
- service restart: `no`
- `.env` mutation: `no`
- learning-to-execution: `no`
- parameter changes: `no`

Learning-log note:

- report-only event opportunity: `event_type=cancel_replace_observation`
- `reprice_decision=reprice_74000`
- `cancel_replace_outcome=old_cancelled_replacement_opened`
- `learning_to_execution_allowed=false`
- `parameter_change_allowed=false`

Validation:

```bash
PYTHONPATH=/root/apps/Crypto/coinbase_bot pytest \
  tests/test_phase_d4_controlled_cancel_replace.py \
  tests/test_live_exit_gate_d4_controlled_cancel_replace.py \
  tests/test_phase_d4_cancel_replace_planner.py
```

Result: `35 passed`.

```bash
PYTHONPATH=/root/apps/Crypto/coinbase_bot pytest \
  tests/test_phase_d4_controlled_cancel_replace.py \
  tests/test_live_exit_gate_d4_controlled_cancel_replace.py \
  tests/test_phase_d4_cancel_replace_planner.py \
  tests/test_phase_d45_real_state_operator_report.py \
  tests/test_phase_d45_historical_exit_operations_report.py \
  tests/test_phase_d45_operator_decision_report.py \
  tests/test_phase_d45_exit_operations_report.py \
  tests/test_phase_d3_open_exit_lifecycle_manager.py \
  tests/test_phase_d3_cancel_closeout_local_reconcile.py \
  tests/test_phase_d5_execution_metrics.py \
  tests/test_phase_d5_learning_log.py
```

Result: `105 passed`.

Compile validation passed for:

- `bot/phase_d4_controlled_cancel_replace.py`
- `tools/run_phase_d4_controlled_cancel_replace.py`
- `tests/test_phase_d4_controlled_cancel_replace.py`

Next step:

Wait for a lifecycle trigger on the new TP1 replacement order at `74000.00`. Do not run another reprice, cancel/replace, lifecycle apply, parameter review or learning automation without a new explicit prompt and ACK.
