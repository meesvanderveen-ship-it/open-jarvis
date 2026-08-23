# D.5 Structured Learning Log Foundation v1

## Purpose

The D.5 structured learning log is a report-only JSON/JSONL audit format for future parameter review. It collects execution and lifecycle observations from fixture/report inputs such as D.5 metrics, D.45 exit operations, historical lifecycle reports and D.4 decision reports.

It never calls Coinbase, submits, cancels, replaces, reprices, applies lifecycle changes, writes trading state, restarts services or changes strategy/execution parameters.

## Schema

Each learning event is a JSON object with `schema_version=1.0` and these core fields when available:

- identity: `generated_at`, `event_type`, `ticker`, `client_order_id`, `exchange_order_id`, `linked_position_id`, `phase`, `source`
- lifecycle: `lifecycle_branch`, `final_outcome`, `blockers`, `safety_drift`
- plan/market: `planned_entry_price`, `planned_exit_price`, `current_market_mid`, `target_distance_abs`, `target_distance_pct`, `target_distance_band`
- fills/no-fills: `actual_fill_price`, `fill_count`, `filled_base`, `filled_quote`, `remaining_size`, `fees`, `no_fill_duration_seconds`, `stale_order_age_seconds`
- quality: `slippage_vs_decision_mid_pct`, `slippage_vs_best_bid_or_ask_pct`
- decisions: `reprice_decision`, `reprice_reason`, `cancel_replace_outcome`, `operator_decision`
- gates: `learning_to_execution_allowed=false`, `parameter_change_allowed=false`, `report_only=true`

## Builder and Exporter

Module:

```bash
bot/phase_d5_learning_log.py
```

CLI:

```bash
python3 tools/show_phase_d5_learning_log.py \
  --lifecycle-fixture lifecycle.json \
  --d5-metrics-fixture d5.json \
  --d45-fixture d45.json \
  --event-type open_no_fill_observation \
  --jsonl
```

The CLI reads only explicit fixture/report files. It writes only to stdout unless `--output` is provided. `--output` is intended for operator-selected export paths or temp-dir tests, not trading state.

## Intended Workflow

1. Collect structured events for a defined time window or event count.
2. Feed the JSONL log into a separate Codex parameter-review task.
3. Codex may propose parameter changes from the log.
4. Proposed changes require tests, review and explicit human approval.
5. No automatic parameter change is allowed from the log itself.

## Boundaries

The active `BTC-USDC` TP1 replacement at `76000.00` remains governed by the D.3/D.45 trigger policy. The learning log does not justify polling, reprice, cancel/replace, lifecycle apply or learning-to-execution.

Any future parameter change must be handled in a separate review prompt and must keep `learning_to_execution_allowed=false` until a separately designed, tested and approved execution gate exists.

