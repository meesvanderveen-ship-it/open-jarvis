# D.6 Governance Evidence Bundle v1

Status: report-only governance and evidence summary.

## Purpose

`bot/phase_d6_governance_evidence_bundle.py` combines approved local safety checks with a compact D.5/D.6 evidence summary from explicit local log paths.

It does not call Coinbase, inspect live orders, mutate trading state, repair local state, approve live actions, optimize parameters, rank settings, or connect learning to execution.

## Included Summaries

- open-order summary from `tools/show_open_orders.py --open-only --json --limit 20`
- function preservation audit status/counts
- D.3 controlled-exit local report summary
- state hash comparison for `state/open_orders.json` and `state/positions.json`
- D.5/D.6 evidence category counts from explicit local event logs
- environment hygiene flags such as whether `bwrap` is on PATH

The bundle stores evidence counts and categories, not raw order payloads.

## CLI

```bash
python3 tools/build_phase_d6_governance_evidence_bundle.py \
  --output reports/d6/governance-evidence.json \
  --markdown-output reports/d6/governance-evidence.md \
  --metadata-sidecar
```

Default evidence input is `logs/order_events.jsonl`. Additional local JSON/JSONL inputs can be supplied with repeated `--evidence-input` flags.

## Safety

Reports are written through the D.6 atomic report writer and set:

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
