# D.6 Report Bundle Writer / Atomic Research Output Writer v1

Status: research-only atomic output helper.

## Purpose

`bot/phase_d6_report_bundle_writer.py` standardizes explicit D.6 report output writes under `reports/d6/`.

It does not run research, optimize parameters, rank reports, approve changes, inspect live orders, write trading state, or call Coinbase.

## Outputs

- JSON report bundles.
- Markdown report bundles.
- Optional `*.metadata.json` sidecars.

All output paths must be under `reports/d6/`. Paths under `state/` and `.env` targets are refused.

## Atomic Write

The writer serializes the report, writes a temporary file in the target directory, then replaces the target path with `os.replace`.

Dry-run mode validates and previews the write result without creating report or metadata files.

## Metadata Sidecar

The optional sidecar records:

- `sha256`
- `generated_at`
- `report_type`
- `phase`
- `source_paths`
- `input_hashes`
- D.6 research-only safety flags

## CLI

```bash
python3 tools/write_phase_d6_report_bundle.py --report-type example --output reports/d6/example.json --metadata-sidecar
python3 tools/write_phase_d6_report_bundle.py --report-type example --output reports/d6/example.md --markdown --dry-run
python3 tools/write_phase_d6_report_bundle.py --content reports/d6/input.json
```

## Safety

The report and write preview set the required D.6 research-only safety flags:

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
