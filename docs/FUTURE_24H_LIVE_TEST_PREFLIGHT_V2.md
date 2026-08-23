# Future 24h Live-Test Preflight v2

This is a template for a future exact-ACK prompt. It is not an approval and must not be used to start live trading by itself.

## Proposed Scope

- Product: `BTC-USDC`.
- Duration: up to 24 hours.
- Max notional: `10 USDC`.
- Order count: exactly one controlled order unless a future prompt states otherwise.
- Post-only preferred.
- No multi-ticker live trading.
- No parameter changes.
- No learning-to-execution.
- No cancel, replace or reprice unless a separate future ACK allows it.

## Required Fresh Local Checks

```bash
python3 tools/show_open_orders.py --open-only --json --limit 20
python3 tools/show_function_preservation_audit.py --fail-on-review
python3 tools/show_phase_d3_controlled_live_exits.py --ticker BTC-USDC --json
sha256sum state/open_orders.json state/positions.json
```

## Required Future ACKs

- `I_APPROVE_BOUNDED_COINBASE_READ_ONLY_PREFLIGHT_FOR_ONE_DAY_LIVE_TEST`
- `I_APPROVE_EXACTLY_ONE_CONTROLLED_LIVE_TEST_ORDER_MAX_10_USDC_BTC_USDC`
- `I_APPROVE_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE_FOR_THIS_ONE_TEST_ORDER`

## Required Evidence Capture

- Preflight state hashes and local safety status.
- Product rules and balances only after read-only ACK.
- Client order id and exchange order id only after submit ACK.
- Local and exchange lifecycle snapshots according to the ACK boundary.
- Fill/no-fill duration.
- Maker/post-only outcome.
- Fee evidence.
- D.5/D.6 rows for post-run human review.
- Final state hashes and open-order status.

## Stop Conditions

- Unexpected local open order before authorized submit.
- Active D.3 exit before authorized submit.
- Missing next-boundary ACK.
- Product rules, balance or order constraints unclear.
- Need for cancel, replace or reprice without separate ACK.
- State hash drift that is not explained.
- Any request to use learning output as execution permission.
