# D.6 Report Lineage / Dependency Graph v1

Status: descriptive research metadata.

## Purpose

`bot/phase_d6_report_lineage.py` builds a lightweight dependency graph from manifest metadata. It helps identify which reports appear to feed other reports and which input references are missing.

It does not rank report importance, approve parameter changes, generate live instructions, or call Coinbase.

## Inputs

- A D.6 report manifest JSON path or report object.
- Optional explicit report paths if no manifest is supplied.

Inputs under `state/` and `.env` paths are rejected.

## Output

- `nodes`
- `edges`
- `source_reports`
- `derived_reports`
- `orphan_reports`
- `missing_input_references`
- `lineage_status`
- warnings, blockers, and safety flags

## Lineage Status

- `complete_for_supplied_reports`
- `partial`
- `insufficient_metadata`
- `blocked`

## CLI

```bash
python3 tools/show_phase_d6_report_lineage.py --manifest reports/d6/manifest.json --json
```

The CLI prints JSON to stdout only.

## Limitations

Lineage is inferred from explicit metadata and known D.6 phase relationships. It is descriptive, not a full provenance proof.
