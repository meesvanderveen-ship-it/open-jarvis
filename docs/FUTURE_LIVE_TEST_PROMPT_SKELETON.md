# Future Controlled Live-Test Prompt Skeleton

Status: template only. This is not approval for a live test.

Use this skeleton only after reviewing the final readiness packet and deciding to create a separate exact ACK prompt.

## Required Context

- Final readiness packet path and hash.
- Current state hash for `state/open_orders.json`.
- Current state hash for `state/positions.json`.
- Result of local open-order check.
- Result of function preservation audit.
- Result of D.3 controlled-exit local report.
- Result of selected D.3/D.4/D.6 readiness regression.
- Disposition for stale denormalized reservation warning.
- Disposition for TP_CLOSE fee evidence gap.
- Disposition for `bwrap` environment warning.

## Required Future Test Definition

- Product.
- Side.
- Maximum notional.
- Size/base constraints.
- Limit price or price logic.
- Order type.
- Post-only behavior.
- Whether Coinbase read-only evidence collection is allowed.
- Whether submit is allowed.
- Whether cancel, replace, or reprice is allowed.
- Whether lifecycle apply is allowed after terminal evidence.
- Stop conditions.

## ACK Matrix

Each allowed boundary must be explicitly stated. Omitted boundaries remain forbidden.

```text
ACK: authorize only <exact bounded action> for <product> with <size/notional> under <order constraints>.

Allowed boundaries:
- Coinbase read-only evidence collection: <yes/no>
- Submit: <yes/no>
- Cancel/replace/reprice: <yes/no>
- Lifecycle apply after terminal evidence: <yes/no>

Forbidden boundaries:
- local repair apply
- dust/manual close
- service restart
- .env/runtime config mutation
- prompt/strategy/risk/parameter mutation
- optimization/search/parameter approval
- learning-to-execution
- sudo/package/system mutation

Stop if:
- local open orders are unexpected
- active D.3 exit is unexpected
- duplicate/oversell risk appears
- state hashes drift unexpectedly
- exchange evidence conflicts with local lifecycle evidence
- any non-authorized boundary becomes necessary
```

Do not combine system maintenance, local repair, parameter work, and live order work in one future prompt.
