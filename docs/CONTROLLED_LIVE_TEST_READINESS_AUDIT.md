# Controlled Live-Test Readiness Audit v1

Status: report-only audit and one-day run plan.

`bot/phase_d6_controlled_live_test_audit_plan.py` answers the pre-live questions that must stay separate from actual live action:

- what remains before a controlled live test;
- whether backlearning was executed or only scaffolded;
- which crypto products have coverage and live lifecycle evidence;
- which missing items block a small controlled live test;
- which data can be collected during a one-day run;
- which ACKs are required for the next boundary.

The audit does not call Coinbase, does not call the OpenAI API, does not submit orders, does not apply lifecycle, does not repair local state, and does not change strategy or parameters.

## CLI

```bash
.venv/bin/python tools/build_controlled_live_test_audit_plan.py \
  --output reports/d6/controlled-live-test-audit-plan-20260601.json \
  --markdown-output reports/d6/controlled-live-test-audit-plan-20260601.md \
  --metadata-sidecar
```

## Expected Interpretation

The audit may mark a future one-product, one-order live-test route as viable for review, but that is not approval. Actual Coinbase read-only preflight, submit, and lifecycle apply remain separately ACK-gated.

Current known non-blocking warnings for a tiny BTC-USDC-only future test:

- multi-crypto D.6 coverage is incomplete;
- cached candle coverage currently exists for BTC-USDC only;
- stale denormalized reservation field remains documented;
- TP_CLOSE fee field gap remains documented;
- `bwrap` is missing on PATH.

Current hard blocker:

- exact future ACKs for Coinbase read-only, live submit, and lifecycle apply are missing.
