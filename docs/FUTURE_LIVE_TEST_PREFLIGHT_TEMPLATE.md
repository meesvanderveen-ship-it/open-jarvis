# Future Controlled Live-Test Preflight Template

Status: template only. This document is not approval for a live test.

> **State-evidence rule — 2026-06-19:** static position assertions in this
> template are not current-state evidence. Before any future operator action,
> use current hashed local state plus separately authorized read-only exchange
> reconciliation; do not infer an empty position set from older documentation.

Use this template only in a future operator prompt that explicitly authorizes the exact bounded action. Keep research, learning, and execution separated.

## Required Local Preconditions

- `python3 tools/show_open_orders.py --open-only --json --limit 20` shows zero open orders.
- `python3 tools/show_function_preservation_audit.py --fail-on-review` returns `ok_observe_only`.
- `python3 tools/show_phase_d3_controlled_live_exits.py --ticker BTC-USDC --json` shows no manageable open position unless the future test explicitly creates one.
- State hashes for `state/open_orders.json` and `state/positions.json` are captured before any authorized boundary.
- D.3/D.4 safety regression and D.6 governance regression are green.
- D.6 safety validation passes for the current readiness report.
- `bwrap` warning is either resolved in a separate maintenance task or explicitly accepted as non-blocking for the future test.

## Required Future Prompt Fields

- Task name and reason for the live test.
- Product, side, size, price logic, order type, post-only behavior, and maximum notional.
- Whether a Coinbase read-only check is authorized before action.
- Whether submit is authorized.
- Whether cancel, replace, or reprice is authorized.
- Whether lifecycle apply is authorized after valid terminal evidence.
- Exact stop conditions.
- Required docs/checkpoint outputs.

## Boundaries That Must Stay Separate

- Coinbase read-only evidence collection.
- Submit.
- Cancel, replace, or reprice.
- Lifecycle apply.
- Local repair apply.
- Dust close or manual close.
- Runtime config, risk, strategy, prompt, or parameter mutation.
- Service restart.
- System package maintenance.
- Any research-to-execution bridge.

## Future ACK Skeleton

The future operator prompt must spell out the exact ACK, for example:

```text
ACK: authorize only <bounded action> for <product> with <size/notional> under <price/order constraints>.
No other live action, repair, config change, package mutation, or parameter mutation is authorized.
Stop if <stop condition list>.
```

Do not combine unrelated live, repair, system, or parameter work in the same future ACK.
