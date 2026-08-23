# D.6 Data Coverage Inventory v1

Timestamp: `2026-05-29T19:05:00Z`

## Purpose

D.6 Data Coverage Inventory v1 is the first research-only layer for the multi-year backtesting program. It defines the ticker/timeframe/window manifest and dry-run Coinbase candle request plan needed for `3y` and `5y` research.

It does not fetch candles, call Coinbase, run a backtest, optimize parameters, write trading state or touch live orders.

## Components

- module: `bot/phase_d6_data_coverage.py`
- CLI: `tools/show_phase_d6_data_coverage.py`
- tests: `tests/test_phase_d6_data_coverage.py`

## Default Universe

The default research universe mirrors the configured default universe:

- `BTC-USDC`
- `ETH-USDC`
- `SOL-USDC`
- `XRP-USDC`
- `ADA-USDC`
- `LINK-USDC`
- `AVAX-USDC`
- `DOGE-USDC`
- `SUI-USDC`
- `LTC-USDC`
- `HBAR-USDC`
- `ATOM-USDC`
- `NEAR-USDC`
- `APT-USDC`
- `INJ-USDC`
- `ARB-USDC`
- `OP-USDC`
- `UNI-USDC`

The CLI can override this with comma-separated or repeatable `--tickers` values.

## Timeframes

Supported now:

- required: `1H`, `4H`, `1D`
- optional: `15M`

Out of scope for v1:

- `5M`
- `1M`

Lower timeframes should be added only for a later targeted fill-model task.

## Research Windows

For each ticker/timeframe pair, the planner emits:

- primary window: `3y`
- extended window: `5y`

Use `--as-of YYYY-MM-DD` to make the report deterministic. The window is modeled as `[as_of - years, as_of)`.

## Chunking Assumption

Coinbase candle request planning assumes a maximum of `350` candles per request. Each report entry includes:

- `requested_start`
- `requested_end`
- `expected_candle_count`
- `planned_chunk_count`
- per-chunk start/end and expected candle count
- Coinbase granularity name
- proposed cache/report paths

No request is executed in v1.

## CLI

Default full manifest:

```bash
python3 tools/show_phase_d6_data_coverage.py --as-of 2026-05-29 --json
```

Subset:

```bash
python3 tools/show_phase_d6_data_coverage.py \
  --as-of 2026-05-29 \
  --tickers BTC-USDC,ETH-USDC \
  --timeframes 1H,4H,1D \
  --years 3,5 \
  --json
```

Explicit output:

```bash
python3 tools/show_phase_d6_data_coverage.py \
  --as-of 2026-05-29 \
  --output reports/d6/coverage/coverage-2026-05-29.json
```

The CLI refuses output paths under `state/`.

## Report-Only Guarantees

Every report includes:

- `research_only=true`
- `no_coinbase_call=true`
- `no_bulk_data_fetch=true`
- `no_live_action=true`
- `state_write_performed=false`
- `learning_to_execution_allowed=false`
- `parameter_change_allowed=false`

The module does not import the Coinbase client and does not read live trading state.

## Next Step

The next safe D.6 task is a separate `D.6 Coinbase Candle Ingest v1` prompt. That task should add read-only candle fetching with chunk limits, cache manifests, retry/rate-limit handling and explicit output paths, but it must still remain separate from live execution and parameter changes.
