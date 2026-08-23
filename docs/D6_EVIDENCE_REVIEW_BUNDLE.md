# D.6 Combined Evidence Review Bundle v2

Status: human-review-only research bundle.

## Purpose

`bot/phase_d6_evidence_review_bundle.py` combines:

- the D.6 parameter candidate inventory,
- D.5 evidence adapter reports,
- D.6 regime segmentation reports,
- D.6 fill-realism evidence adapter reports,

into one descriptive review bundle for future human research review.

The bundle is not a parameter review, not an optimizer, not a ranking report, and not a live-trading instruction.

## Inputs

- Optional D.5 evidence adapter report JSON paths.
- Optional regime segmentation report JSON paths.
- Optional fill-realism evidence adapter report JSON paths.
- The parameter inventory is built in-process from static local inventory definitions.

Inputs under `state/` and `.env` paths are rejected.

## Report Sections

- `source_summary`
- `parameter_inventory_summary`
- `d5_evidence_summary`
- `regime_summary`
- `fill_realism_summary`
- `fill_realism_warning_counts`
- `fill_realism_blocker_counts`
- `warning_counts`
- `blocker_counts`
- `review_readiness`
- `suggested_next_research_steps`
- `prohibited_interpretations`
- safety flags

## Review Readiness

Possible values:

- `insufficient_evidence`
- `exploratory_only`
- `ready_for_human_research_review`
- `blocked_by_quality`

Readiness does not approve parameter changes. It only describes whether the research pack has enough non-blocked evidence to be worth human review.

## CLI

```bash
python3 tools/show_phase_d6_evidence_review_bundle.py \
  --d5-evidence reports/d6/d5-evidence.json \
  --regime-report reports/d6/regime.json \
  --fill-realism-evidence reports/d6/fill-realism-evidence.json \
  --json
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

## Required Manual Workflow

Any future parameter change still requires:

1. separate Codex review;
2. reproducible research report;
3. tests;
4. human review;
5. explicit approval;
6. separate config-change task;
7. observe-only or shadow validation before live use.

## Limitations

- The bundle summarizes evidence counts and blockers only.
- It does not compute statistical significance.
- It does not connect learning outputs to execution.
