# D.6 Guardrail Summary Adapter v1

Status: research-only adapter.

## Purpose

`bot/phase_d6_guardrail_summary_adapter.py` summarizes existing D.6 guardrail-style JSON reports into compact rows for the parameter review pack.

It does not run optimization, rank parameters, approve changes, call Coinbase, inspect live orders, or mutate trading state.

## Inputs

- Explicit local JSON report paths, or in-process report objects in tests.
- Intended report types:
  - dataset quality report,
  - dataset quality aggregate,
  - walk-forward split report,
  - out-of-sample degradation report,
  - overfitting / trial-accounting report,
  - cost assumption report,
  - fill-realism report.

Inputs under `state/` and `.env` paths are rejected.

## Output

Each `guardrail_summary_row` includes:

- `guardrail_id`
- `source_file`
- `report_phase`
- `report_status`
- `guardrail_type`
- `guardrail_status`
- `warning_count`
- `blocker_count`
- `warnings`
- `blockers`
- `implicated_parameter_categories`
- `evidence_strength`
- `human_review_required=true`
- `parameter_review_approved=false`
- `parameter_change_allowed=false`

## Guardrail Status

- `pass`
- `warning`
- `blocked`
- `insufficient`

These statuses are descriptive and do not approve parameter changes.

## CLI

```bash
python3 tools/show_phase_d6_guardrail_summary_adapter.py --report reports/d6/guardrails.json --json
```

The CLI prints JSON to stdout only.

## Safety

Reports set:

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
