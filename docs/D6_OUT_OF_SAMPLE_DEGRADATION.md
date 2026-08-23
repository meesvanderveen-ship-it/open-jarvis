# D.6 Out-of-Sample Degradation Checks v1

D.6 Out-of-Sample Degradation Checks v1 is a research-only diagnostic layer for inspecting train -> validation -> test degradation in existing D.6 evidence.

It is descriptive only. It is not a parameter review, strategy recommendation, optimization process, parameter search, ranking engine or live-readiness check.

## Components

- module: `bot/phase_d6_oos_degradation.py`
- CLI: `tools/show_phase_d6_oos_degradation.py`
- tests: `tests/test_phase_d6_oos_degradation.py`

## Scope

V1 can:

- build full train/validation/test degradation rows from explicit local candle files and cost scenarios;
- consume a compact D.6 Research Review Pack JSON and run limited validation -> test diagnostics;
- report baseline and fixed Level-0 signal degradation separately;
- emit conservative warnings for single file, single signal, single split configuration, unavailable train metrics, blocked evidence and severe degradation.

V1 does not include regime segmentation. Regime segmentation remains a later separate scaffold.

## Input Policy

Allowed inputs:

- explicit local normalized D.6 candle JSON files;
- explicit cost scenarios;
- an existing D.6 Research Review Pack JSON.

Forbidden:

- implicit ticker universe expansion;
- Coinbase fetches;
- live trading state;
- paths under `state/`;
- `.env` targets.

## CLI

From explicit local candles:

```bash
python3 tools/show_phase_d6_oos_degradation.py \
  --candles research_data/coinbase/candles/product=BTC-USDC/timeframe=1D/study_window=3y.json \
  --cost-scenario zero_cost_reference,conservative_slippage \
  --split-mode holdout \
  --train-count 210 \
  --validation-count 70 \
  --test-count 70 \
  --json
```

From an existing review pack:

```bash
python3 tools/show_phase_d6_oos_degradation.py \
  --review-pack reports/d6/review/review-pack.json \
  --json
```

Optional explicit outputs:

```bash
python3 tools/show_phase_d6_oos_degradation.py \
  --candles /tmp/d6/BTC-USDC-1D.json \
  --output reports/d6/oos/oos-degradation.json \
  --markdown-output reports/d6/oos/oos-degradation.md
```

Default behavior is stdout-only unless `--output` or `--markdown-output` is supplied.

## Degradation Fields

Rows may include:

- `average_train_net_return_pct`
- `average_validation_net_return_pct`
- `average_test_net_return_pct`
- `train_to_validation_degradation_pct_points`
- `validation_to_test_degradation_pct_points`
- `train_to_test_degradation_pct_points`
- `degradation_class`
- `blocked_range_count`
- warnings

Positive degradation values mean the earlier range had higher return than the later range.

## Classes

V1 uses conservative classes:

- `no_oos_check_available`
- `stable_or_improving`
- `mild_degradation`
- `moderate_degradation`
- `severe_degradation`
- `blocked_or_unusable`

These classes are diagnostic labels, not rankings and not trading recommendations.

## Compact Review-Pack Limitation

D.6 Research Review Pack v1 stores compact baseline and signal rows. It does not retain full train metrics. When OOS checks consume only a review-pack JSON, train -> validation and train -> test checks are unavailable. The report will set train fields to `null` and emit `train_metrics_unavailable_for_some_or_all_rows`.

For full train/validation/test diagnostics, run OOS checks from explicit local candle files.

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
- `strategy_parameter_mutation_allowed=false`
- `runtime_config_mutation_allowed=false`
- `human_review_required=true`
- `parameter_review_allowed=false`
- `parameter_review_approved=false`
- `broader_signal_expansion_requires_human_approval=true`
- `contains_rankings=false`
- `contains_recommendations=false`
- `contains_live_instructions=false`

## Non-Ranking Policy

The report must not:

- rank tickers;
- rank cost scenarios;
- rank signals;
- select a best report;
- propose parameter changes;
- imply live readiness.

## Limitations

- Descriptive OOS degradation only.
- No parameter review approval.
- No optimization or parameter search.
- No formal PBO or Deflated Sharpe Ratio.
- No statistical significance claim.
- No regime segmentation in v1.
- No fill realism, orderbook depth, post-only queue or partial-fill model.
- Not live trading guidance.

## Next Step

A future separate task may add `D.6 Regime Segmentation Scaffold v1` or expand OOS diagnostics with explicit out-of-sample degradation thresholds after more local datasets exist.
