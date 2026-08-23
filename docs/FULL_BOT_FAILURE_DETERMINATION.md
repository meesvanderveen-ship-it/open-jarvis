# Full Bot Failure Determination Matrix v1

This diagnostic is report-only. It includes all 18 configured USDC tickers and explains why each ticker is or is not progressing through D.6 candidate, calibrated intent, Full Bot Orchestrator, Maker BUY adapter, Near-Miss/Fresh Review, Phase-C guard and future ACK-gated live-readiness.

It does not submit orders, call Coinbase write endpoints, cancel/replace orders, mutate config, mutate strategy/risk parameters or write trading state.

## Command

```bash
python3 tools/build_full_bot_failure_determination_matrix.py \
  --all-configured-tickers \
  --json-out reports/d6/full-bot-failure-determination-matrix-$(date -u +%Y%m%d).json \
  --markdown-out reports/d6/full-bot-failure-determination-matrix-$(date -u +%Y%m%d).md
```

## Inputs

The tool loads the latest available local artifacts:

- `reports/d6/d6-multi-order-intent-preview-calibrated-*.json`
- `reports/d6/full-bot-orchestrator-*.json`
- `reports/d6/full-bot-maker-buy-live-adapter-*.json`
- `reports/d6/full-bot-maker-buy-live-adapter-post-review-*.json`
- `reports/d6/full-bot-near-miss-phase-c-review-*.json`
- `reports/d6/full-bot-fresh-phase-c-evidence-*.json`
- `state/open_orders.json`
- `state/positions.json`

Absent configured tickers are still emitted as `no_candidate_seen`.

## Interpretation

Root causes are intentionally operational:

- `needs_fresh_judge_review` and `needs_deterministic_live_risk` mean the ticker may be worth review, but is not live-ready.
- `adapter_selection_cap` means `max_new_orders_per_cycle=2` hid a candidate from adapter selection; this is diagnostic only and does not change the live cap.
- `phase_c_ready` still requires a future exact ACK before any live submit.
- `stale_candidate_needs_refresh` means the candidate must be refreshed before review or live-readiness analysis.

Future live submit remains BUY-only, maker/limit-only, max 20 USDC per order, max 5 open orders total, max 2 new orders per cycle unless separately changed, max 1 open order per ticker, exact ACK gated and Phase-C guarded.
