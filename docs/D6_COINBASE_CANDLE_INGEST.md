# D.6 Coinbase Candle Ingest v1

Timestamp: `2026-05-29T19:25:00Z`

## Purpose

D.6 Coinbase Candle Ingest v1 is a research-only, read-only candle ingestion layer. It consumes D.6 Data Coverage Inventory chunk plans and can fetch/cache Coinbase OHLCV candles for explicit bounded selections.

It does not run backtests, optimize parameters, touch active orders, write trading state or change live behavior.

## Components

- module: `bot/phase_d6_coinbase_candle_ingest.py`
- CLI: `tools/fetch_phase_d6_coinbase_candles.py`
- tests: `tests/test_phase_d6_coinbase_candle_ingest.py`

## Default Behavior

The CLI defaults to dry-run:

```bash
python3 tools/fetch_phase_d6_coinbase_candles.py \
  --as-of 2026-05-29 \
  --tickers BTC-USDC \
  --timeframes 1D \
  --years 3 \
  --json
```

Dry-run:

- makes no Coinbase calls
- writes no cache files
- emits the planned selection and manifest shape to stdout

## Explicit Fetch

Fetch mode must be explicit and bounded:

```bash
python3 tools/fetch_phase_d6_coinbase_candles.py \
  --as-of 2026-05-29 \
  --tickers BTC-USDC \
  --timeframes 1D \
  --years 3 \
  --max-chunks 1 \
  --fetch \
  --output-root research_data/coinbase/candles \
  --manifest-output reports/d6/coverage/btc-1d-3y-manifest.json \
  --json
```

Safety limits:

- `--fetch` is required for any Coinbase read
- `--max-chunks` is required for fetch mode
- a run cannot exceed the module's bounded max fetch-call budget
- output paths under `state/` are refused
- `.env` paths are refused
- only the read-only `get_public_candles` method is allowed

## Candle Records

Normalized records include:

- `product_id`
- `timeframe`
- `start`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `source`
- `fetched_at`

Candles are sorted and deduplicated by `start`. Open/incomplete candles are dropped during raw normalization when their interval has not closed relative to `fetched_at`.

## Manifest

Each ingest report includes:

- ticker
- timeframe
- study window
- chunks requested/fetched
- candle count
- first/last candle start
- gap count
- errors
- output path
- report-only flags

Top-level safety flags:

- `research_only=true`
- `no_coinbase_write_call=true`
- `no_live_action=true`
- `state_write_performed=false`
- `no_backtest=true`
- `no_optimization=true`
- `learning_to_execution_allowed=false`
- `parameter_change_allowed=false`

## Cache Layout

Default cache path:

```text
research_data/coinbase/candles/
  product=BTC-USDC/
    timeframe=1D/
      study_window=3y.json
```

Manifests should go under:

```text
reports/d6/coverage/
```

Neither cache nor manifest outputs should be treated as live trading state.

## Error Handling

API errors are recorded in the manifest. The ingest does not fabricate missing candles. For failed chunks it writes an empty candle file for that bounded selection and reports the error, allowing the operator to retry or inspect without hidden data corruption.

## Next Step

The next D.6 task should be a small, explicit sample data fetch or a baseline backtest scaffold using fixture/cached candle files. Do not run a full-universe multi-year download, optimization or parameter review from this ingest task.
