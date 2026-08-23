# Full Bot Fresh Judge/Risk Evidence Runner

`bot/full_bot_fresh_judge_risk_evidence_runner.py` builds report-only evidence packets for current full-bot maker BUY candidates.

It does not submit live orders, call Coinbase write endpoints, write trading state, mutate `.env`, start the bot, enable SELL, enable market orders, enable D.3 exits, enable replication, or promote candidates without real evidence.

## Inputs

By default the CLI loads the latest local D.6 artifacts from `reports/d6`:

- `full-live-parameter-readiness-gate-*.json`
- `full-bot-workflow-completeness-audit-*.json`
- `full-bot-failure-determination-matrix-*.json`
- `full-bot-maker-buy-live-adapter-post-review-*.json`
- `full-bot-near-miss-phase-c-review-*.json`
- `d6-multi-order-intent-preview-calibrated-*.json`
- `full-bot-orchestrator-*.json`

Optional real judge/risk evidence may be supplied with `--fresh-review-evidence`. The expected shape is:

```json
{
  "by_ticker": {
    "XRP-USDC": {
      "judge": {
        "decision": "approve_trade",
        "side": "BUY",
        "approved": true
      },
      "risk": {
        "mode": "deterministic_live_risk",
        "approved": true,
        "accepted": true,
        "risk_approved": true
      }
    }
  }
}
```

If this evidence is omitted or incomplete, the runner emits `fresh_judge_review_required` and `deterministic_live_risk_review_required`.

## Candidate Selection

The runner includes:

- all P1 candidates from the failure matrix
- selected adapter candidates
- cap-hidden adapter candidates
- fresh judge/risk candidate lists from the readiness/failure reports
- candidates already close to Phase-C readiness

Each evidence packet records ticker, setup, proposed price, quote, target, invalidation, stale status, local orderbook freshness if present, required judge input, required deterministic risk input, current blockers and any real evidence found.

## Commands

Build the report:

```bash
python3 tools/build_full_bot_fresh_judge_risk_evidence_runner.py \
  --json-out reports/d6/full-bot-fresh-judge-risk-evidence-$(date -u +%Y%m%d).json \
  --markdown-out reports/d6/full-bot-fresh-judge-risk-evidence-$(date -u +%Y%m%d).md
```

With real evidence:

```bash
python3 tools/build_full_bot_fresh_judge_risk_evidence_runner.py \
  --fresh-review-evidence reports/d6/real-fresh-judge-risk-evidence.json \
  --json-out reports/d6/full-bot-fresh-judge-risk-evidence-$(date -u +%Y%m%d).json \
  --markdown-out reports/d6/full-bot-fresh-judge-risk-evidence-$(date -u +%Y%m%d).md
```

Actual submit remains a separate ACK-gated action and must not be run from this evidence sprint.
