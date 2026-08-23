# D.6 Cost-Aware Split Baseline Report v1

D.6 Cost-Aware Split Baseline Report v1 combines local normalized candle files, D.6 walk-forward splits, D.6 metrics helpers and one explicit D.6 fee/slippage/spread cost scenario.

It is research-only. It does not call Coinbase, fetch data, generate signals, optimize parameters, rank cost scenarios, rank parameters, change live settings or produce live trading recommendations.

## Components

- module: `bot/phase_d6_cost_aware_split_baseline.py`
- CLI: `tools/show_phase_d6_cost_aware_split_baseline.py`
- tests: `tests/test_phase_d6_cost_aware_split_baseline.py`

## Scope

- Input: one local normalized D.6 candle JSON file.
- Split modes: `holdout`, `rolling`, `expanding`.
- Baseline v1: `buy_hold` only.
- Cost scenarios: one explicit scenario from `D.6 Fee/Slippage Assumption Pack v1`.
- Output: JSON report to stdout by default, or to an explicit non-`state/` path.

This module is separate from `D.6 Split-Aware Baseline Report v1` so existing split-aware report semantics remain unchanged.

## Cost Model

For each train/validation/test range:

1. Entry cost is applied to the initial quote before buying base.
2. Mark-to-market equity applies the exit cost haircut.
3. Final quote applies exit cost at the last close.
4. Total cost estimate is reported as entry cost quote plus exit cost quote.

This is a deterministic candle-only approximation. It is not a post-only maker fill model, orderbook model or Coinbase fee-tier inference.

## CLI

```bash
python3 tools/show_phase_d6_cost_aware_split_baseline.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --cost-scenario conservative_slippage \
  --split-mode holdout \
  --train-count 210 \
  --validation-count 70 \
  --test-count 70 \
  --json
```

Use `--output reports/d6/<name>.json` only when a persisted research report is intentionally needed. Paths under `state/` and `.env` paths are refused.

## Report Shape

Top-level fields include:

- `product_id`
- `timeframe`
- `candles_path`
- `baseline_type`
- `cost_scenario`
- `cost_assumptions`
- `derived_costs`
- split configuration and split count
- dataset quality summary
- per-split `train`, `validation`, and `test` cost-aware metrics
- aggregate validation/test summaries
- warnings, blockers and limitations
- safety flags

Per-range metrics include:

- return metrics
- drawdown metrics
- exposure metrics
- trade metrics
- cost metrics
- warnings

## Safety Flags

Reports include:

- `research_only=true`
- `no_live_action=true`
- `no_coinbase_call=true`
- `state_write_performed=false`
- `no_bulk_fetch=true`
- `no_optimization=true`
- `parameter_search_performed=false`
- `signal_generation_performed=false`
- `live_recommendation=false`
- `learning_to_execution_allowed=false`
- `parameter_change_allowed=false`

## Limitations

- `buy_hold` only in v1.
- One cost scenario per report.
- No ranking of cost scenarios.
- No signal generation.
- No optimization or parameter search.
- No post-only queue, orderbook depth or partial-fill modeling.
- Not a live trading recommendation.

## Next Step

A future separate task may use this adapter as the cost-aware baseline comparison before implementing a fixed Level-0 signal scaffold. Do not use this report to change live parameters.
