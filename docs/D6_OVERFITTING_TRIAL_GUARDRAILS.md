# D.6 Overfitting / Trial-Accounting Guardrails v1

D.6 Overfitting / Trial-Accounting Guardrails v1 adds a conservative research-hygiene layer around D.6 evidence packs.

It is descriptive only. It does not calculate formal Probability of Backtest Overfitting, Deflated Sharpe Ratio, statistical significance, parameter rankings, strategy rankings or live recommendations.

## Components

- module: `bot/phase_d6_overfitting_guardrails.py`
- CLI: `tools/show_phase_d6_overfitting_guardrails.py`
- tests: `tests/test_phase_d6_overfitting_guardrails.py`

## Scope

V1 reports:

- file count;
- cost scenario count;
- fixed signal count;
- split configuration count;
- baseline report count;
- signal report count;
- total evidence report count;
- descriptive trial count;
- estimated degrees of research freedom;
- guardrail warnings;
- blockers;
- conservative `guardrail_class`.

Supported source modes:

- consume an existing D.6 Research Review Pack JSON;
- build a D.6 Research Review Pack from explicit local candle files and cost scenarios.

Inputs are explicit local research files only. Paths under `state/` and `.env` targets are refused.

## CLI

From explicit local candles:

```bash
python3 tools/show_phase_d6_overfitting_guardrails.py \
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
python3 tools/show_phase_d6_overfitting_guardrails.py \
  --review-pack reports/d6/review/review-pack.json \
  --json
```

Optional explicit outputs:

```bash
python3 tools/show_phase_d6_overfitting_guardrails.py \
  --review-pack reports/d6/review/review-pack.json \
  --output reports/d6/guardrails/guardrails.json \
  --markdown-output reports/d6/guardrails/guardrails.md
```

The default behavior is stdout-only unless `--output` or `--markdown-output` is supplied.

## Guardrail Classes

V1 uses conservative classes:

- `exploratory_only`: evidence is useful for research inspection but too narrow or trial-heavy for parameter review.
- `usable_for_limited_research`: evidence has enough breadth for limited research inspection, still not parameter review approval.
- `insufficient_for_parameter_review`: source evidence is missing, blocked, or claims rankings/recommendations/live instructions.

`parameter_review_allowed=false` in every v1 report.

## Warnings

Potential warnings include:

- `limited_file_or_ticker_breadth`
- `multiple_cost_scenarios_inspected_not_ranked`
- `single_fixed_signal_only`
- `single_split_configuration_only`
- `trial_count_growing_track_cherry_picking_risk`
- `trial_count_high_requires_separate_research_approval`
- `research_degrees_of_freedom_growing`
- `source_claims_rankings_review_required`
- `source_claims_recommendations_review_required`
- `source_claims_live_instructions_blocked`

These warnings are not rankings and do not select winners.

## Non-Ranking Policy

The guardrail report must not:

- rank tickers;
- rank cost scenarios;
- rank signals;
- rank strategies;
- rank parameters;
- choose a best report;
- propose parameter changes;
- imply live readiness.

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
- `parameter_review_approved=false`
- `contains_rankings=false`
- `contains_recommendations=false`
- `contains_live_instructions=false`

## Limitations

- Descriptive trial accounting only.
- No formal PBO or Deflated Sharpe Ratio.
- No statistical significance claim.
- No hidden optimization, parameter search or parameter review approval.
- No fill realism, orderbook depth, post-only queue or partial-fill model.
- Not live trading guidance.

## Next Step

A future separate task may add out-of-sample degradation checks or regime segmentation. Broader signal expansion, full multi-ticker research expansion, optimization or parameter review still require separate explicit approval.
