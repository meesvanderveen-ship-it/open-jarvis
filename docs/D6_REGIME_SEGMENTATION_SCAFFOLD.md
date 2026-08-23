# D.6 Regime Segmentation Scaffold v1

Status: research-only scaffold.

## Purpose

`bot/phase_d6_regime_segmentation.py` labels local historical candle windows with simple regime descriptors. It is designed to help future D.6 review packs compare evidence across market contexts without optimizing trading parameters.

It does not fetch candles, call Coinbase, produce live signals, rank markets, recommend trades, or approve parameter changes.

## Inputs

- One explicit local normalized candle JSON path.
- Required candle fields:
  - `start`
  - `open`
  - `high`
  - `low`
  - `close`
  - `volume`

Inputs under `state/` and `.env` paths are rejected.

## Output Fields

- `product_id`
- `timeframe`
- `candle_count`
- `first_candle_start`
- `last_candle_start`
- `window_size`
- `step_size`
- `regime_window_count`
- `regime_counts`
- `window_rows`
- `warnings`
- `blockers`
- `usable_for_future_research`
- safety flags

Window rows include simple descriptive metrics:

- `window_return`
- `avg_abs_return`
- `range_pct`
- `trend_slope_proxy`
- `regime_labels`

## Regime Labels

- `uptrend`
- `downtrend`
- `range`
- `high_volatility`
- `low_volatility`
- `compression`
- `breakout_context`

Blocked reports may include dataset-level blockers such as `insufficient_candles_for_window` or `missing_required_candle_fields`.

## CLI

```bash
python3 tools/show_phase_d6_regime_segmentation.py --candles research_data/coinbase/candles/example.json --window-size 20 --step-size 20 --json
```

The CLI prints to stdout only.

## Safety Boundaries

- no Coinbase calls
- no live state reads
- no strategy optimization
- no parameter search
- no buy/sell recommendations
- no live trading instructions
- no parameter review approval

## Limitations

- Regime labels use simple fixed descriptive thresholds.
- Thresholds are not optimized and must not be interpreted as strategy parameters.
- This scaffold is for segmentation and review context only.
