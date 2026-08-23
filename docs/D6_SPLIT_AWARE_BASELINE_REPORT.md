# D.6 Split-Aware Baseline Report v1

D.6 Split-Aware Baseline Report v1 is a research-only adapter that combines local normalized candle files, D.6 dataset quality readiness, D.6 walk-forward split windows, and D.6 metrics helpers.

It does not fetch data, optimize parameters, rank parameters, generate new signals, or produce live trading recommendations.

## Scope

- Input: one local normalized D.6 candle JSON file.
- Split modes: `holdout`, `rolling`, `expanding`.
- Baseline v1: `buy_hold` only.
- Output: JSON report to stdout by default, or to an explicit non-`state/` path.
- Safety: report-only, research-only, no Coinbase calls, no live execution.

## CLI

```bash
python3 tools/show_phase_d6_split_aware_baseline.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --split-mode holdout \
  --train-count 210 \
  --validation-count 70 \
  --test-count 70 \
  --baseline buy_hold \
  --initial-quote 1000 \
  --fee-pct 0.0040 \
  --json
```

Use `--output reports/d6/<name>.json` only when a persisted research report is intentionally needed. Paths under `state/` and `.env` paths are refused.

## Report Shape

The report includes:

- `product_id`, `timeframe`, candle count and first/last candle start.
- split configuration and split count.
- dataset quality summary from the walk-forward split scaffold.
- per-split `train`, `validation`, and `test` range metrics.
- return, drawdown, exposure, trade, and fee metrics from the D.6 metrics foundation.
- aggregate summary fields such as average validation/test return and worst test drawdown.
- warnings, blockers, limitations, and explicit safety flags.

Required safety flags remain:

- `research_only=true`
- `no_live_action=true`
- `no_coinbase_call=true`
- `state_write_performed=false`
- `no_bulk_fetch=true`
- `no_optimization=true`
- `parameter_search_performed=false`
- `signal_generation_performed=false`
- `learning_to_execution_allowed=false`
- `parameter_change_allowed=false`

## Limitations

- `buy_hold` is the only supported baseline in v1.
- No post-only maker fill model exists here.
- No slippage/spread model exists here.
- The report is not a strategy recommendation and must not be used to change live parameters.
- Future Level-0 signal work should remain a separate task with its own tests and safety review.

## Future Work

The next safe D.6 step is a fixed Level-0 signal scaffold or a fee/slippage assumption pack. Either should consume the same dataset quality, walk-forward split, and metrics layers without enabling optimization or parameter changes.
