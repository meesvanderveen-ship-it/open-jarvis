# D.6 Parameter Candidate Inventory v1

## Purpose

`D.6 Parameter Candidate Inventory v1` lists local candidate parameters that may eventually be evaluated by D.6/D.5 research. It maps each candidate to the categories in `docs/D6_PARAMETER_BACKLEARNING_WORKFLOW.md` and records the evidence needed before any future human review.

The inventory is not optimization, ranking, recommendation, parameter review or live trading guidance.

## Components

- module: `bot/phase_d6_parameter_inventory.py`
- CLI: `tools/show_phase_d6_parameter_inventory.py`
- tests: `tests/test_phase_d6_parameter_inventory.py`

## Report Fields

Each parameter row includes:

- `parameter_name`
- `category`
- `category_label`
- `source_file`
- `source_symbol`
- `default_value`
- `parameter_type`
- `safety_class`
- `evidence_source_needed`
- `eligible_for_future_review`
- `parameter_change_allowed=false`
- `notes`

Safety classes:

- `research_only_candidate`
- `human_review_required`
- `high_risk_manual_only`
- `never_auto_change`

## CLI

Stdout-only full inventory:

```bash
python3 tools/show_phase_d6_parameter_inventory.py --json
```

Optional category filter:

```bash
python3 tools/show_phase_d6_parameter_inventory.py \
  --category d3_controlled_exit,d4_dynamic_order_management \
  --json
```

The tool has no `--output` option. It writes no report files and does not write `state/`.

## Safety Flags

Reports include:

- `research_only=true`
- `no_coinbase_call=true`
- `no_live_action=true`
- `state_write_performed=false`
- `no_bulk_fetch=true`
- `no_optimization=true`
- `parameter_search_performed=false`
- `parameter_change_allowed=false`
- `learning_to_execution_allowed=false`
- `contains_rankings=false`
- `contains_recommendations=false`
- `contains_live_instructions=false`
- `runtime_config_mutation_allowed=false`
- `strategy_parameter_mutation_allowed=false`
- `human_review_required=true`
- `parameter_review_approved=false`

## Boundaries

The inventory must not:

- call Coinbase;
- inspect or interact with live orders;
- submit/cancel/replace/reprice;
- apply lifecycle evidence;
- mutate `.env`, runtime config, prompts or trading state;
- write under `state/`;
- search, optimize, rank, recommend or approve parameters;
- connect learning to execution.

## Limitations

- Curated static inventory, not a full AST discovery engine.
- Defaults are source defaults when safely visible, not current runtime `.env` values.
- Some dynamic policy fields are listed as `caller_supplied`.
- The report does not judge whether a parameter should change.

## Next Step

Build `D.5 Execution Outcome -> D.6 Evidence Adapter v1` or `D.6 Regime Segmentation Scaffold v1`. Both should remain report-only and avoid parameter ranking/search.
