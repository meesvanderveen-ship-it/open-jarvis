# D.6 Parameter Review Pack Scaffold v1

Status: human-review-only scaffold.

## Purpose

`bot/phase_d6_parameter_review_pack.py` combines the local parameter inventory, evidence bundle summaries, and guardrail summaries into category-level review sections.

The pack helps a human decide what to investigate next. It does not identify best parameters, propose concrete values, rank settings, approve runtime changes, or connect learning to execution.

## Inputs

- Optional parameter inventory report path, or local inventory built in-process.
- Optional combined evidence review bundle path.
- Optional D.5 evidence report paths.
- Optional regime report paths.
- Optional fill-realism evidence report paths.
- Optional guardrail summary path.
- Optional raw guardrail report paths.

All paths are explicit local paths. Inputs under `state/` and `.env` are rejected.

## Review Sections

The pack emits one section for each parameter category:

- `universe_market_selection`
- `market_data_features`
- `gatekeeper_routing`
- `entry_signal`
- `position_sizing_risk`
- `d2_position_executor`
- `d3_controlled_exit`
- `d4_dynamic_order_management`
- `d5_execution_learning`
- `ai_prompt_judge`

Each section includes:

- `category`
- `candidate_count`
- `evidence_count`
- `warning_count`
- `blocker_count`
- `evidence_strength_counts`
- `sample_size_warning`
- `guardrail_status`
- `review_status`
- `prohibited_interpretations`
- `parameter_review_approved=false`
- `parameter_change_allowed=false`

## Review Status

- `insufficient_evidence`
- `exploratory_only`
- `blocked`
- `ready_for_human_review`

`ready_for_human_review` means only that a human may inspect the evidence. It does not approve a parameter change.

## CLI

```bash
python3 tools/show_phase_d6_parameter_review_pack.py \
  --evidence-review-bundle reports/d6/evidence-bundle.json \
  --guardrail-summary reports/d6/guardrail-summary.json \
  --json
```

The CLI prints JSON to stdout only.

## Safety

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

## Required Manual Boundary

Any future parameter change requires a separate task, reproducible evidence, tests, human approval, and observe-only or shadow validation before live use.
