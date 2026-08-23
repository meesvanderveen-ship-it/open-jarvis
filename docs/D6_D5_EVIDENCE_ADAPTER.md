# D.6 / D.5 Evidence Adapter v1

Status: research-only scaffold.

## Purpose

`bot/phase_d6_d5_evidence_adapter.py` converts local D.5-style metrics, structured learning logs, and lifecycle/order-event JSON or JSONL records into D.6-compatible evidence rows for later human review.

The adapter summarizes evidence only. It does not optimize, rank, recommend, approve parameter changes, inspect live orders, or call Coinbase.

## Inputs

- Explicit local JSON or JSONL paths.
- Intended sources:
  - D.5 execution metrics reports.
  - D.5 structured learning logs.
  - local lifecycle/order-event records used as historical evidence.
  - fixture records in tests.

Inputs under `state/` and `.env` paths are rejected by the shared D.6 research path guard.

## Evidence Rows

Each evidence row includes:

- `evidence_id`
- `generated_at`
- `source_type`
- `source_file`
- `event_type`
- `ticker`
- `order_label`
- `lifecycle_stage`
- `outcome_class`
- `metric_name`
- `metric_value`
- `metric_unit`
- `evidence_categories`
- `parameter_categories_implicated`
- `parameter_candidates_implicated`
- `evidence_strength`
- `warnings`
- `blockers`
- `human_review_required=true`
- `parameter_change_allowed=false`
- `parameter_review_approved=false`

## Evidence Categories

- `fill_quality`
- `no_fill_duration`
- `cancel_replace_outcome`
- `post_only_fill_behavior`
- `maker_taker_liquidity`
- `slippage_fee_realization`
- `reservation_drift`
- `duplicate_or_oversell_incidents`
- `lifecycle_terminal_handling`
- `tiny_notional_lifecycle_overhead`
- `stale_label_or_workflow_confusion`
- `parameter_categories_implicated`

## CLI

```bash
python3 tools/show_phase_d6_d5_evidence_adapter.py --input reports/example.json --json
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

- Evidence strength is descriptive, not statistical proof.
- Candidate mappings are conservative hints for human review packs.
- The adapter does not resolve live lifecycle state and must not be used as an order monitor.
