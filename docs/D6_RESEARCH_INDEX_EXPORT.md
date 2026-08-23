# D.6 Research Index Export v1

Status: human-facing research governance export.

## Purpose

`bot/phase_d6_research_index_export.py` combines:

- report manifest metadata,
- report lineage metadata,
- research safety validation,

into one JSON or Markdown export for human review.

It does not approve parameter changes, live actions, or learning-to-execution.

## Inputs

- Manifest report path.
- Lineage report path.
- Safety validation report path.
- Optional direct report paths if manifest, lineage, or validation should be built in-process.

Inputs under `state/` and `.env` are rejected.

## CLI

JSON stdout:

```bash
python3 tools/show_phase_d6_research_index_export.py --manifest reports/d6/manifest.json --lineage reports/d6/lineage.json --safety-validation reports/d6/safety.json
```

Markdown stdout:

```bash
python3 tools/show_phase_d6_research_index_export.py --manifest reports/d6/manifest.json --lineage reports/d6/lineage.json --safety-validation reports/d6/safety.json --markdown
```

Optional output is allowed only under `reports/d6/`.

## Markdown Sections

- Safety disclaimer
- Report manifest summary
- Reproducibility status
- Lineage summary
- Safety validation summary
- Blockers
- Warnings
- Missing metadata
- Human review checklist
- Explicit conclusion:
  - no parameter changes approved
  - no live actions approved
  - no learning-to-execution enabled

## Safety

The export sets all required D.6 research-only safety flags and keeps `parameter_review_approved=false`.
