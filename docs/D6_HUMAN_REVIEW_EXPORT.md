# D.6 Human Review Export Bundle v1

Status: human-facing research export.

## Purpose

`bot/phase_d6_human_review_export.py` wraps a D.6 parameter review pack for human reading. It can emit JSON or Markdown.

The export is not a parameter approval, not a config-change task, not a live signal, and not an execution instruction.

## Inputs

- Optional parameter review pack JSON path.
- If no path is provided, a local empty-scaffold parameter review pack can be built in-process.

Inputs under `state/` and `.env` are rejected.

## CLI

JSON stdout:

```bash
python3 tools/show_phase_d6_human_review_export.py --review-pack reports/d6/parameter-review-pack.json
```

Markdown stdout:

```bash
python3 tools/show_phase_d6_human_review_export.py --review-pack reports/d6/parameter-review-pack.json --markdown
```

Optional output is allowed only under an explicit `reports/d6/` path:

```bash
python3 tools/show_phase_d6_human_review_export.py \
  --review-pack reports/d6/parameter-review-pack.json \
  --markdown \
  --output reports/d6/human-review.md
```

## Markdown Sections

- Title
- Source summary
- Safety disclaimer
- Review readiness
- Blockers
- Warnings
- Category sections
- Evidence summaries
- Human review checklist
- Explicit conclusion that no parameter changes are approved
- Next research-only steps

## Safety

The export sets:

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

- Markdown is a presentation layer only.
- It does not compute additional evidence.
- It does not approve or propose runtime changes.
