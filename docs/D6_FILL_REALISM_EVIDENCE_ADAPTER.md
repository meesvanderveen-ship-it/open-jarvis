# D.6 Fill Realism Evidence Adapter v1

Status: research-only adapter.

## Purpose

`bot/phase_d6_fill_realism_evidence_adapter.py` converts fill-realism assumption rows into D.6 evidence rows that can be consumed by the combined evidence review bundle.

It does not optimize, rank, recommend, approve parameter changes, inspect live orders, or call Coinbase.

## Inputs

- Fill-realism assumption report JSON paths, or
- explicit raw local JSON/JSONL paths that are first converted through the fill-realism assumption pack.

Inputs under `state/` and `.env` paths are rejected.

## Evidence Categories

- `post_only_fill_behavior`
- `fill_probability_context`
- `no_fill_duration`
- `cancel_replace_churn`
- `spread_distance_context`
- `tiny_notional_lifecycle_overhead`
- `maker_taker_liquidity`
- `cost_fill_realism_interaction`

## Implicated Parameter Categories

The adapter may tag:

- `d3_controlled_exit`
- `d4_dynamic_order_management`
- `d5_execution_learning`
- `d2_position_executor`
- `market_data_features`

These tags are review hints only. They are not parameter proposals.

## CLI

```bash
python3 tools/show_phase_d6_fill_realism_evidence_adapter.py --input /tmp/orders.json --json
python3 tools/show_phase_d6_fill_realism_evidence_adapter.py --fill-realism-report /tmp/fill-realism.json --json
```

The CLI prints to stdout only.

## Safety Flags

The report sets:

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

## Limitations

- Evidence strength is descriptive.
- Candidate hints are conservative review labels.
- The adapter does not connect evidence to execution.
