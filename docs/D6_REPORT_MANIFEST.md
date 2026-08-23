# D.6 Report Manifest / Reproducibility Index v1

Status: research-only metadata index.

## Purpose

`bot/phase_d6_report_manifest.py` catalogs explicit local D.6 research reports and records reproducibility metadata.

It does not run research, optimize parameters, rank reports, approve changes, inspect live orders, or call Coinbase.

## Inputs

- Explicit local report paths.
- Optional explicit directories under `reports/d6/`.
- Supported file extensions: `.json`, `.jsonl`, `.md`.

Inputs under `state/` and `.env` paths are rejected. Symlink report paths are rejected.

## Manifest Row Fields

- `report_id`
- `source_path`
- `path_kind`
- `file_extension`
- `file_size_bytes`
- `modified_time_utc`
- `sha256`
- `detected_phase`
- `detected_status`
- `generated_at_from_report`
- `report_type`
- `source_summary`
- `safety_flags_detected`
- `missing_safety_flags`
- `warning_count`
- `blocker_count`
- `input_paths_detected`
- `output_paths_detected`
- `reproducibility_status`
- `human_review_required=true`
- `parameter_review_approved=false`
- `parameter_change_allowed=false`

## Reproducibility Status

- `reproducible_metadata_present`
- `missing_hashable_inputs`
- `missing_safety_flags`
- `insufficient_metadata`
- `blocked`

## CLI

```bash
python3 tools/show_phase_d6_report_manifest.py --report reports/d6/example.json --json
python3 tools/show_phase_d6_report_manifest.py --directory reports/d6 --json
```

The CLI prints JSON to stdout only.

## Safety

The manifest treats explicit `source_paths` in report bundles as hashable input metadata for reproducibility status.

The report sets the required D.6 research-only safety flags, including `parameter_change_allowed=false`, `contains_rankings=false`, `contains_recommendations=false`, and `parameter_review_approved=false`.
