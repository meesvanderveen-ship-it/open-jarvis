# D.6 Research Review Pack v1

D.6 Research Review Pack v1 bundles existing D.6 research layers into one compact human-review artifact.

It is research-only. It does not call Coinbase, fetch data, inspect live orders, emit live signals, optimize, search parameters, rank tickers, rank scenarios, rank signals, approve parameter review or recommend live trading changes.

## Components

- module: `bot/phase_d6_research_review_pack.py`
- CLI: `tools/build_phase_d6_research_review_pack.py`
- tests: `tests/test_phase_d6_research_review_pack.py`

## Scope

V1 includes:

- dataset quality aggregate;
- cost-aware `buy_hold` baseline bundle;
- fixed Level-0 `fixed_sma_cross_5_20` signal bundle;
- fee/slippage/spread cost assumption summary;
- descriptive trial-accounting preview;
- warnings, blockers, limitations and prohibited interpretations.

Inputs are explicit local normalized D.6 candle JSON files and explicit cost scenarios. One split configuration is used per pack.

Paths under `state/` and `.env` targets are refused.

## CLI

```bash
python3 tools/build_phase_d6_research_review_pack.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --cost-scenario zero_cost_reference,conservative_slippage \
  --split-mode holdout \
  --train-count 210 \
  --validation-count 70 \
  --test-count 70 \
  --json
```

Optional explicit outputs:

```bash
python3 tools/build_phase_d6_research_review_pack.py \
  --candles /tmp/d6/BTC-USDC-1D.json,/tmp/d6/ETH-USDC-1D.json \
  --cost-scenario standard_fee_only,conservative_slippage \
  --output reports/d6/review/review-pack.json \
  --markdown-output reports/d6/review/review-pack.md
```

The default behavior is stdout-only unless `--output` or `--markdown-output` is supplied.

## Report Shape

Top-level sections include:

- `input_summary`
- `dataset_quality_summary`
- `dataset_quality_reports`
- `baseline_evidence_summary`
- `baseline_evidence_rows`
- `signal_evidence_summary`
- `signal_evidence_rows`
- `cost_assumption_summary`
- `trial_accounting_preview`
- `warning_counts`
- `warnings`
- `blockers`
- `limitations`
- `prohibited_interpretations`
- `suggested_next_research_steps`
- safety flags

The trial-accounting preview is descriptive only. It records how many files, scenarios, fixed signals and evidence reports were included. It is not a formal overfitting statistic, Probability of Backtest Overfitting estimate or Deflated Sharpe Ratio.

## Non-Ranking Policy

The pack must not:

- choose a best ticker;
- choose a best cost scenario;
- choose a best signal;
- rank parameters;
- rank strategies;
- produce live recommendations;
- imply live readiness;
- approve parameter changes.

Valid interpretations include:

- dataset quality is or is not adequate for further research;
- baseline evidence exists under explicit assumptions;
- fixed Level-0 signal evidence exists under explicit assumptions;
- warnings and blockers need human review;
- more research is needed before any parameter review.

## Prohibited Interpretations

Reports include explicit prohibited interpretations:

- `do_not_infer_best_ticker`
- `do_not_infer_best_cost_scenario`
- `do_not_infer_best_signal`
- `do_not_infer_parameter_change`
- `do_not_infer_live_readiness`
- `do_not_use_as_execution_signal`
- `do_not_use_as_parameter_review_approval`

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
- `fixed_parameters_only=true`
- `strategy_parameter_mutation_allowed=false`
- `runtime_config_mutation_allowed=false`
- `human_review_required=true`
- `parameter_review_approved=false`
- `contains_rankings=false`
- `contains_recommendations=false`
- `contains_live_instructions=false`

## Limitations

- Compact human-review artifact only.
- Fixed `fixed_sma_cross_5_20` signal only in v1.
- Cost-aware `buy_hold` baseline only in v1.
- One split configuration per pack.
- No formal PBO, Deflated Sharpe Ratio or overfitting statistic.
- No fill realism, orderbook depth, post-only queue or partial-fill model.
- Not a parameter review and not live trading guidance.

## Next Step

A future separate task should add formal overfitting/trial-accounting guardrails before broader signal expansion, multi-ticker research expansion or parameter-review preparation.
