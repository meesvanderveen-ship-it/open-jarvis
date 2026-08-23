# D.6 Fee/Slippage Assumption Pack v1

D.6 Fee/Slippage Assumption Pack v1 defines reusable research-only cost scenarios for future D.6 reports.

It does not call Coinbase, fetch market data, run a backtest, generate signals, optimize parameters, rank scenarios, change live settings or produce live trading recommendations.

## Components

- module: `bot/phase_d6_cost_assumptions.py`
- CLI: `tools/show_phase_d6_cost_assumptions.py`
- tests: `tests/test_phase_d6_cost_assumptions.py`

## Scenarios

Predefined v1 scenarios:

- `zero_cost_reference`: unrealistic gross-reference scenario.
- `low_cost_maker_like`: low-cost maker-like research placeholder, not a Coinbase fee schedule.
- `standard_fee_only`: fee-only scaffold matching the existing D.6 default per-side fee assumption.
- `conservative_slippage`: fee, slippage and spread haircut placeholder for candle-only research.
- `stress_cost`: higher-cost sensitivity placeholder.

These names are not rankings. They are labels for explicit assumptions.

## Derived Costs

Each scenario reports:

- fee assumptions:
  - `maker_fee_pct`
  - `taker_fee_pct`
  - `entry_fee_pct`
  - `exit_fee_pct`
- slippage assumptions:
  - `entry_slippage_pct`
  - `exit_slippage_pct`
- spread assumptions:
  - `spread_pct`
  - `entry_spread_cost_pct`
  - `exit_spread_cost_pct`
- derived costs:
  - `entry_cost_pct`
  - `exit_cost_pct`
  - `round_trip_cost_pct`
  - `conservative_cost_pct`

For v1, the spread is split evenly across entry and exit. This is a simple research placeholder, not a post-only fill model.

## CLI

Catalog:

```bash
python3 tools/show_phase_d6_cost_assumptions.py --scenario all --json
```

Single scenario:

```bash
python3 tools/show_phase_d6_cost_assumptions.py \
  --scenario conservative_slippage \
  --json
```

Optional explicit report output:

```bash
python3 tools/show_phase_d6_cost_assumptions.py \
  --scenario all \
  --output reports/d6/costs/d6-cost-assumptions.json
```

Paths under `state/` and `.env` targets are refused.

## Warnings

Warnings may include:

- `unrealistic_zero_cost_assumption`
- `slippage_not_modeled`
- `spread_not_modeled`
- `stress_cost_assumption`
- `not_live_fee_schedule`
- `not_strategy_recommendation`
- `not_parameter_ranking`
- `not_parameter_search`
- `not_optimization`

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

This pack does not:

- model orderbook depth;
- model post-only queue position;
- model partial fills;
- infer actual Coinbase fee tiers;
- select a best scenario;
- change any backtest result by itself;
- approve any live parameter or execution change.

## Next Step

A future separate task can integrate these scenarios into split-aware baseline reports or a fixed Level-0 signal scaffold. That integration must remain research-only and must not perform optimization, parameter search, ranking or live recommendations.
