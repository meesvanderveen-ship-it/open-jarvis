# D.6 Final Readiness Packet v1

Status: report-only consolidation packet.

## Purpose

`bot/phase_d6_final_readiness_packet.py` combines the latest local readiness report, governance evidence bundle, readiness index, selected regression evidence, state-hash comparison, environment hygiene, and future ACK boundaries into one final packet under `reports/d6/`.

The packet exists to reduce future manual check loops before a controlled live-test prompt review. It is not live-test approval.

## CLI

```bash
.venv/bin/python tools/build_phase_d6_final_readiness_packet.py \
  --readiness-report reports/d6/live-test-readiness-20260601.json \
  --governance-evidence-report reports/d6/governance-evidence-bundle-20260601.json \
  --readiness-index-report reports/d6/live-test-readiness-index-20260601.json \
  --readiness-regression-status pass \
  --readiness-regression-tests-passed 151 \
  --readiness-regression-command ".venv/bin/python -m pytest -q <selected D3/D4/D6 readiness suite>" \
  --output reports/d6/final-readiness-packet-20260601.json \
  --markdown-output reports/d6/final-readiness-packet-20260601.md \
  --metadata-sidecar
```

## Packet Contents

- Gate 0-5 status summary.
- Remaining work split into:
  - must finish before future prompt review;
  - useful but not blocking;
  - separate exact ACK-gated work;
  - deferrable work.
- Regression evidence for the selected readiness suite.
- D.6 report input references.
- State hash comparison.
- Environment hygiene status.
- Future prompt packet references.

## Safety

The final readiness packet is report-only and sets:

- `research_only=true`
- `no_coinbase_call=true`
- `no_live_action=true`
- `state_write_performed=false`
- `no_optimization=true`
- `parameter_search_performed=false`
- `parameter_change_allowed=false`
- `learning_to_execution_allowed=false`
- `contains_rankings=false`
- `contains_recommendations=false`
- `contains_live_instructions=false`
- `human_review_required=true`
- `parameter_review_approved=false`

It does not call Coinbase, call the OpenAI API, write trading state, apply lifecycle events, repair local state, restart services, mutate configuration, install packages, or connect research outputs to execution.
