# Reflection Adaptive Sidecar

`tools/run_reflection_adaptive_report_sidecar.py` runs the reflection, adaptive policy, candidate analysis, lab status, and governor status tools in a fixed report-only sequence.

Outputs:

- `reports/sidecars/reflection-adaptive-sidecar-latest.json`
- `reports/sidecars/reflection-adaptive-sidecar-latest.md`
- `logs/reflection_adaptive_sidecar.jsonl`

The sidecar does not run inside the trading loop because these analyses can be refreshed asynchronously. Trading execution remains governed by deterministic live safety checks, existing profile gates, and explicit operator ACKs.

Safety contract:

- no Coinbase submit, cancel, replace, apply, or market order action
- no `.env` mutation
- no service stop, start, or restart
- no production `open_orders.json` or `positions.json` mutation
- no live mutation of `state/approved_parameter_profile.json`
- no parameter activation

Timer templates exist under `deploy_templates/` only. Do not install or enable them without operator approval.

Operator review flow:

1. Run `python3 tools/run_reflection_adaptive_report_sidecar.py --json`.
2. Review `reports/sidecars/reflection-adaptive-sidecar-latest.md`.
3. Review `reports/adaptive_policy/analysis/parameter-candidate-analysis-latest.md`.
4. Activation remains blocked unless the Adaptive Policy Lab creates a candidate, the Autonomous Parameter Governor gates pass, and the exact required ACK/hash flow is followed.

## Direction History

Each sidecar run refreshes the report-only adaptive candidate flow, which appends candidate direction history under:

```text
reports/adaptive_policy/history/adaptive-policy-candidate-history.jsonl
```

The sidecar summary exposes this path and the number of history rows seen. Parameter Candidate Analysis uses the same history to show `history_items_available`, `last_3_direction_entries`, and direction-stability status. Repeated matching parameter/scope/direction runs can move observed stability toward `3/3`; this remains analysis-only and does not enable activation by itself.
