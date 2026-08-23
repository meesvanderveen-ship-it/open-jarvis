# D.6 Research Safety Validator v1

Status: research-only safety validator.

## Purpose

`bot/phase_d6_research_safety_validator.py` validates that supplied D.6 reports preserve required research-only boundaries.

It does not inspect live orders, call Coinbase, mutate state, rank parameters, recommend changes, or approve parameter review.

## Required Flag Checks

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

## Prohibited Phrase Checks

- `best parameter`
- `change parameter`
- `recommendation`
- `live signal`
- `execute this trade`
- `approved parameter`

## Output

- `validation_rows`
- `pass_count`
- `warning_count`
- `blocker_count`
- `missing_flag_counts`
- `prohibited_phrase_hits`
- `overall_status`
- safety flags

## Overall Status

- `pass`
- `warning`
- `blocked`
- `insufficient_metadata`

## CLI

```bash
python3 tools/show_phase_d6_research_safety_validator.py --report reports/d6/example.json --json
python3 tools/show_phase_d6_research_safety_validator.py --manifest reports/d6/manifest.json --json
```

The CLI prints JSON to stdout only.
