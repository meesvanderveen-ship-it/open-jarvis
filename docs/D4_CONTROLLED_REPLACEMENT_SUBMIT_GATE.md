# D.4 Controlled Replacement Submit Gate

## Purpose

This gate integration makes the central live-exit gate aware of the D.4 controlled cancel/replace route without enabling general live exits. It is code/test/docs only: it does not cancel, replace, submit, poll Coinbase, mutate `.env`, or write trading state.

The previous D.4 controlled cancel/replace preflight for BTC-USDC target `76000.00` correctly stopped before cancel because replacement submit was not guaranteed by the central gate.

## Source

Allowed D.4 source:

- `phase_d4_controlled_cancel_replace`

Required ACK:

- `I_UNDERSTAND_AND_APPROVE_D4_TRAILING_CANCEL_REPLACE_ONE_SHOT`

The existing D.3 source remains unchanged. This integration does not add a broad autonomous SELL permission.

## One-Shot Arming

The D.4 replacement submit gate can become green only with process-local one-shot arming:

- `one_shot_d4_replacement_submit_armed_process_local=true`
- `env_mutation=false`
- `scope=single_runner_process_only`

Default runtime flags remain safe:

- `ENABLE_LIVE_EXIT_ORDERS=false`
- `AUTONOMOUS_ALLOW_EXITS=false`
- `ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=false`
- `PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=true`

Without one-shot arming, the D.4 source stays blocked even with the correct ACK.

## Safety Requirements

The gate requires all of the following:

- exact source `phase_d4_controlled_cancel_replace`
- exact ACK
- process-local one-shot arming
- cancel-first route
- replacement only after confirmed cancel
- side `SELL`
- `post_only=true`
- `reduce_only_local=true`
- linked position present
- exactly one replacement candidate
- no duplicate open exit
- no oversell
- reserved and available base are sufficient for replacement size
- target price respects `price_increment`
- replacement size respects `base_increment`
- estimated quote is at least `min_order_quote`

Failure returns explicit blockers and audit fields. The gate report always includes:

- `no_coinbase_call=true`
- `no_live_action=true`
- `general_live_exits_released=false`
- `autonomous_exits_allowed=false`

## Current BTC-USDC Implication

This integration only prepares the replacement submit gate for a future D.4 controlled cancel/replace retry. It does not retry the live route. The current TP1 remains open at `84800.00` until a separate controlled cancel/replace prompt runs all preflight gates again.

## Tests

Focused test:

```bash
PYTHONPATH=. pytest -o cache_dir=/tmp/coinbase_bot_pytest_cache \
  tests/test_live_exit_gate_d4_controlled_cancel_replace.py
```

Expected result: `12 passed`.

Combined regression with D.3/D.4/D.5/D45 and the existing live gate: `85 passed`.

Compile validation: `python3 -m py_compile bot/live_exit_gate.py` passed.

## Next Step

If the operator still chooses `76000.00`, run a separate D.4 Controlled Cancel/Replace retry prompt. That future prompt must re-check D.45 state, lifecycle evidence, market/product rules, dry-run planner output, and this gate before any cancel attempt.
