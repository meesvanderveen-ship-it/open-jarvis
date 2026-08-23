# D.6 Live-Test Readiness Governance Report v1

Status: report-only readiness harness.

## Purpose

`bot/phase_d6_live_test_readiness.py` builds a local readiness report for a future controlled live-test planning prompt. It combines:

- current local lifecycle checks;
- state-hash before/after comparison;
- D.3 controlled-exit local status;
- the D.6 governance evidence bundle, when supplied;
- environment hygiene such as whether `bwrap` is on PATH;
- readiness gates and future ACK boundaries.

The report is not a live-test prompt and does not authorize live trading.

## CLI

```bash
python3 tools/build_phase_d6_live_test_readiness_report.py \
  --governance-bundle reports/d6/governance-evidence-bundle-20260601.json \
  --output reports/d6/live-test-readiness-20260601.json \
  --markdown-output reports/d6/live-test-readiness-20260601.md \
  --metadata-sidecar
```

If `--output` is omitted, the report is printed to stdout. File output is restricted by the D.6 atomic report writer and must be under `reports/d6/`.

## Gates

- Gate 0: live lifecycle parked by local checks.
- Gate 1: local state hygiene understood, including stale denormalized reservation and fee evidence gap.
- Gate 2: regression readiness tracked for D.3/D.4/D.6 checks.
- Gate 3: research/report governance remains human-review-only.
- Gate 4: environment hygiene tracked, including the `bwrap` PATH warning.
- Gate 5: future live-test design remains blocked until exact operator ACK.

## Safety

The report sets the standard D.6 safety flags:

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

The CLI runs approved local commands only. It does not call Coinbase, write trading state, apply lifecycle events, repair local state, restart services, mutate configuration, install packages, or bridge research outputs into execution.
