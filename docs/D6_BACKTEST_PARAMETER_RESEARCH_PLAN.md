# D.6 Backtest Parameter Research Plan

Timestamp: `2026-05-29T18:45:00Z`

## Executive Recommendation

Build D.6 as a research-only subsystem with its own historical-data cache, backtest reports, parameter-search outputs and D.5-compatible summaries. Do not connect D.6 outputs to live execution, runtime config mutation or strategy parameter changes.

Use a combined horizon:

- collect up to `5 years` of Coinbase candles where available
- use `3 years` as the primary cross-ticker robust comparison window
- use `5 years` as an extended stress/regime window for tickers with sufficient history
- report coverage gaps per ticker and avoid ranking a newer coin unfairly against older coins

First safe implementation task: **D.6 Data Coverage Inventory v1**. It should create a read-only/offline coverage planner and fixture-tested report schema, but not fetch bulk history in the first pass.

## Safety Boundary

D.6 is research-only:

- no Coinbase write calls
- no live action
- no cancel/replace/submit/reprice
- no lifecycle apply
- no trading-state writes on real state
- no service restart
- no `.env` mutation
- no learning-to-execution
- no automatic parameter changes
- no strategy/execution parameter mutation
- no active live order interaction

Any future parameter change requires a separate Codex review, tests, human review and explicit approval. D.5 remains hard-gated with `learning_to_execution_allowed=false` and `parameter_change_allowed=false`.

## Local Context

Relevant existing pieces:

- `bot/config.py` has the default allowed universe and many candidate parameters.
- `bot/market_data.py` already maps `15M`, `1H`, `4H`, `1D` to Coinbase candle granularities and enriches indicators.
- `bot/phase_d2_position_executor.py` defines TP, stop, fee/edge, slice and trailing defaults.
- `bot/phase_d4_trailing_preview.py` defines trailing/reprice preview inputs and fail-closed conditions.
- `bot/phase_d5_execution_metrics.py` and `bot/phase_d5_learning_log.py` define report-only metrics/log outputs.
- D.45 historical and exit reports already provide route-level lifecycle reporting.

The active live order remains out of scope. D.6 should use historical data and fixtures only.

## Data Horizon

Recommended approach:

1. Coverage inventory for all tickers and timeframes.
2. Primary research window: trailing `3 years` ending at a fixed cutoff date.
3. Extended research window: trailing `5 years` for tickers with full or near-full coverage.
4. Newer-asset mode: use all available data, but score separately and label as coverage-limited.

Why both:

- `3 years` is more likely to include the full active universe, including newer listings.
- `5 years` captures broader crypto regimes for BTC/ETH and older alts.
- A parameter must not be promoted if it only works in the 5-year older-coin subset or only in the 3-year newer-coin subset.

Coverage report fields:

- ticker
- timeframe
- requested_start / requested_end
- first_available_candle / last_available_candle
- candle_count
- missing intervals
- gap count and max gap
- available_years
- coverage_class: `full_5y`, `full_3y`, `partial`, `insufficient`
- excluded_from_portfolio_score reason, if any

## Timeframes

Required:

- `1H`: primary operational trading/backtest clock
- `4H`: trend/regime alignment, matching current `PRIMARY_INTERVAL_HOURS=4`
- `1D`: macro/regime filters, higher-timeframe risk state

Optional:

- `15M`: exit timing, no-fill/stale and post-only fill approximation
- `5M`: only for selected final candidates or post-only fill sensitivity checks
- `1M`: only if performance/storage budget is acceptable and the question requires fill timing

Do not start with 1m/5m for full-universe optimization. First establish correctness and broad parameter stability at `1H/4H/1D`, then add `15M` for execution realism.

## Ticker Universe

Start with the default active universe from `BotConfig.allowed_tickers`:

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

Initial priority:

1. Core liquidity: `BTC-USDC`, `ETH-USDC`, `SOL-USDC`
2. Existing/default universe with likely longer history: `XRP-USDC`, `ADA-USDC`, `LINK-USDC`, `AVAX-USDC`, `DOGE-USDC`, `LTC-USDC`, `ATOM-USDC`, `UNI-USDC`
3. Newer/listing-limited assets: `SUI-USDC`, `APT-USDC`, `INJ-USDC`, `ARB-USDC`, `OP-USDC`, `HBAR-USDC`, `NEAR-USDC`

The coverage report decides final inclusion per study window.

## Parameter Groups

### Entry Thresholds

Research candidates:

- expensive judge gate thresholds: min gate confidence, synth confidence, bull score, max bear score
- pending plan thresholds: min confidence, trigger score, max chase distance
- spread cap: `max_spread_pct`
- cooldown: `cooldown_minutes`
- candidate ranking limits: max candidates for deep analysis, priority candidates, breadth relaxation minimum
- RSI/ADX/EMA/Donchian/Bollinger-derived thresholds in deterministic feature gates, where present

Excluded from automatic mutation:

- model names
- API keys
- live execution flags
- safety switches
- ACK strings

### Regime Filters

Research candidates:

- 4h/1d EMA trend filters
- ADX threshold by timeframe
- Bollinger width/compression threshold
- Donchian breakout proximity
- market breadth relaxation threshold
- BTC regime filter for alt entries
- volatility/ATR filters for no-trade zones

### No-Fill / Stale Policy

Research candidates:

- no-fill duration before review
- stale order age threshold
- target-distance bands: near/approaching/far
- monitor-vs-reprice recommendation thresholds
- repeated unchanged `OPEN/open` suppression policy

### TP1/TP2 And Exit Distances

Research candidates:

- minimum expected net edge
- reward-to-fee ratio
- reward-to-risk ratio
- TP1 distance from entry/risk
- TP2 distance above TP1
- slice fractions: TP1/TP2/RUNNER
- time-limit hours

### D.4 Reprice And Trailing

Research candidates:

- reprice bands for far/approaching/near target
- activation profit pct
- trailing distance pct
- refresh tolerance pct
- cooldown seconds between candidates
- stale book seconds
- candidate replacement distance from current bid/ask

### Stops / Invalidation

Research candidates:

- stop distance fallback
- ATR-based stop multiplier
- EMA break invalidation
- range-low invalidation buffer
- time stop after no progress
- break-even/move-stop-after-TP1 logic

### Position Sizing / Risk

Research candidates:

- default quote size
- max notional
- max open positions
- max daily loss guard
- max order quote for Phase C/D.3
- max open exit orders
- max new orders/cancels/replaces per cycle

Sizing research must report sensitivity separately from signal quality; do not optimize size to hide weak entries.

### Product Rules / Min Order Constraints

Research candidates:

- min quote eligibility fallback
- base increment rounding
- price increment rounding
- dust/residual classification threshold

These should be modeled, not tuned into unsafe behavior.

### Post-Only Fill Assumptions

Research candidates:

- candle-cross fill rule
- required touch-through distance
- spread/slippage haircut
- maker non-fill probability by distance and age
- fill delay assumption
- cancel/replace cost/friction assumption

## Data Source Plan

Initial source: Coinbase Advanced Trade historical candles.

The Coinbase candle endpoint returns OHLCV buckets for one product and supports granularities including `ONE_MINUTE`, `FIVE_MINUTE`, `FIFTEEN_MINUTE`, `ONE_HOUR`, `FOUR_HOUR`, and `ONE_DAY`; the documented default/max limit is `350` candles per request. Use chunked downloads per ticker/timeframe/window.

Planned cache layout:

```text
research_data/
  coinbase/
    candles/
      product=BTC-USDC/
        timeframe=1H/
          part-YYYY-MM.parquet
          _coverage.json
    product_rules/
      product=BTC-USDC.json
    books_optional/
      product=BTC-USDC/
        date=YYYY-MM-DD.jsonl
    trades_optional/
      product=BTC-USDC/
        date=YYYY-MM-DD.jsonl
```

Rules:

- never write under `state/`
- never mutate `.env`
- use fixed run ids and manifests for reproducibility
- store raw response metadata and normalized candles separately
- sort and de-duplicate candles by start timestamp
- drop incomplete/open candles for research runs
- record API errors and coverage gaps instead of silently filling data

Coinbase product book and market trades can improve execution modeling. Product book provides bid/ask levels and spread fields; market trades/ticker data provides recent trades plus best bid/ask. These are useful for future Level 2 fill modeling, but should not block the candle-first baseline.

## Fill Model Levels

Level 0: candle-cross approximation

- BUY limit fills if candle low touches or crosses the limit after signal time
- SELL limit fills if candle high touches or crosses the limit after signal time
- assumes immediate fill on touch
- fastest, least realistic
- acceptable only for baseline signal research

Level 1: conservative candle model

- requires price to cross beyond the limit by a configurable buffer
- applies spread/slippage/fee haircut
- delays fill by one or more bars unless the cross is decisive
- applies non-fill probability or deterministic haircut for post-only maker orders
- models stale/no-fill, cancel/replace count and reprice frequency

Level 2: trades/orderbook-enhanced model

- uses historical trades and sampled orderbook/top-of-book where available
- estimates queue/fill probability from distance to bid/ask, spread, volume and time at level
- models post-only rejection/crossing risk
- required before trusting small-edge reprice/trailing conclusions

Candle-only post-only simulation cannot know queue priority, exact spread path inside a candle, maker/taker rejection timing or whether touch volume was enough to fill the bot's order.

## Open-Source Reference Scan

Use these projects as design inspiration only; do not migrate runtime.

- Freqtrade: useful patterns for local data directories, exported backtest results, pairlists, fees, timeframe-detail backtests and hyperopt loss functions. Its docs also emphasize reproducible/static pairlists for backtesting.
- Freqtrade hyperopt: useful pattern for separating parameter spaces, repeated backtests, objective/loss functions, random-state reproducibility and drawdown-aware losses.
- Hummingbot V2 controllers/executors: useful architecture pattern for keeping controllers separate from finite order lifecycle executors.
- Hummingbot executors: useful order lifecycle vocabulary for create/refresh/cancel/close flows, without importing its runtime.
- vectorbt: useful for fast pandas/NumPy/Numba-style parameter sweeps and portfolio metrics once the strategy is vectorizable.

Local code remains authoritative for safety semantics.

References:

- Coinbase candles/product book/trades docs: `https://coinbase-cloud.mintlify.app/api-reference/advanced-trade-api/rest-api/products/get-product-candles`, `get-product-book`, `get-market-trades`
- Freqtrade backtesting and hyperopt docs: `https://docs.freqtrade.io/en/stable/backtesting/`, `https://www.freqtrade.io/en/stable/hyperopt/`
- Hummingbot V2 strategies/controllers/executors docs: `https://hummingbot.org/strategies/v2-strategies/`
- vectorbt docs: `https://vectorbt.dev/`

## Validation Design

Use walk-forward validation with strict information boundaries:

- train window: fit/select parameter ranges
- validation window: choose candidates and reject unstable ranges
- test window: final out-of-sample score, untouched until candidate freeze
- roll forward and repeat

Initial windows:

- `18 months train / 6 months validation / 6 months test`, rolling by `3 months`
- for 3-year coverage-limited assets: `12 months train / 3 months validation / 3 months test`, rolling by `1-3 months`
- for 5-year full assets: include a second pass with `24/6/6`

Regime splits:

- bull trend
- bear trend
- sideways/range
- high volatility
- low volatility
- liquidity/spread stress
- BTC-led vs alt-led periods

Scoring levels:

- per ticker
- per timeframe
- per regime
- portfolio aggregate
- worst-ticker and worst-regime penalties

## Overfitting Controls

Controls:

- require minimum trades per train/validation/test window
- require parameter stability across adjacent windows
- prefer robust parameter plateaus over single best values
- penalize train-to-test degradation
- reject single-coin/single-regime winners
- cap parameter grid size and pre-register search ranges
- hold out final test periods until candidate freeze
- include fees, spread/slippage and no-fill assumptions
- compare against a current-parameter baseline and simple naive baselines
- report "do not change" when evidence is weak

Candidate promotion rule:

- candidate must beat current baseline on median portfolio score
- candidate must not materially worsen worst-ticker/worst-regime drawdown
- candidate must pass at least two fill-model levels, or be labeled candle-only preliminary
- candidate must have clear operational interpretation

## Metrics

Core performance:

- net return
- max drawdown
- Sharpe and Sortino where enough samples exist
- Calmar
- profit factor
- expectancy
- winrate
- average win/loss
- average and median trade duration
- exposure time

Execution/lifecycle:

- fill probability
- no-fill duration
- stale-order count
- reprice frequency
- cancel/replace count
- post-only rejection/crossing proxy
- fee and slippage impact
- maker/taker assumption sensitivity
- partial fill rate, if modeled

Robustness:

- worst ticker result
- worst regime result
- train/validation/test degradation
- parameter stability score
- number of trades per window
- coverage class impact
- sensitivity to fill model level

## Output Reports

D.6 should produce:

- data coverage report
- current-parameter baseline backtest report
- parameter search report
- walk-forward validation report
- fill-model sensitivity report
- candidate parameter report
- rejected/unsafe parameter report
- D.5 learning-log compatible JSONL summary
- "do not change" recommendation when evidence is weak

Report output layout:

```text
reports/d6/
  coverage/
  baseline/
  search/
  walk_forward/
  candidates/
  d5_learning_exports/
```

Do not write D.6 reports into trading state.

## D.5 And Future Codex Review Flow

Expected flow:

1. D.6 generates research reports and D.5-compatible JSONL summaries.
2. Operator feeds selected JSONL/report bundle into a separate Codex parameter-review prompt.
3. Codex may propose parameter changes.
4. Proposed changes require tests, human review and explicit approval.
5. Only a later implementation task may change config/defaults.
6. Live execution remains disabled from learning unless a separately designed and approved gate exists.

D.5 event mapping:

- no-fill/stale outcomes -> `open_no_fill_observation`
- fill outcomes -> `partial_fill_observation` / `filled_observation`
- terminal outcomes -> `terminal_observation`
- reprice outcomes -> `reprice_decision_observation` / `cancel_replace_observation`
- parameter candidate summaries -> research-only `operator_decision_observation` or D.6 summary records, not execution commands

## Implementation Roadmap

### D.6.1 Data Coverage Inventory v1

Docs/code scope:

- define static ticker/timeframe manifest
- define cache paths under `research_data/` or `reports/d6/`
- build fixture-only coverage report tests
- no bulk fetch in first pass
- no state writes

### D.6.2 Coinbase Candle Ingest v1

- chunked candle downloader with max-350 request windows
- dry-run planner mode
- cache manifest and coverage report
- retry limits and rate-limit backoff
- no live trading client methods beyond read-only market data

### D.6.3 Baseline Backtest v1

- current-parameter baseline on `1H/4H/1D`
- Level 0 fill model
- fees and product-rule constraints included
- report-only output

### D.6.4 Fill Model v1

- add `15M` detail mode
- Level 1 conservative post-only model
- no-fill/stale/reprice metrics

### D.6.5 Parameter Search v1

- constrained grid/random/Bayesian search
- parameter spaces pre-registered
- current baseline locked
- no runtime config changes

### D.6.6 Walk-Forward Validation v1

- rolling windows
- out-of-sample reports
- robustness scoring
- candidate promotion/rejection

### D.6.7 D.5 Export v1

- JSONL summaries compatible with D.5 learning log
- explicit gates: `learning_to_execution_allowed=false`, `parameter_change_allowed=false`

## First Safe Implementation Task

Task name: **D.6 Data Coverage Inventory v1**

Deliverables:

- `bot/phase_d6_data_coverage.py` or equivalent small module
- `tools/show_phase_d6_data_coverage.py` with fixture/dry-run inputs only
- `tests/test_phase_d6_data_coverage.py`
- docs update with cache/report schema

Acceptance criteria:

- uses the configured default ticker universe
- emits requested 3-year and 5-year windows
- emits required timeframes `1H`, `4H`, `1D` and optional `15M`
- marks all outputs research-only
- writes no trading state
- makes no Coinbase calls unless a future prompt explicitly asks for read-only coverage probing
- compile/tests pass

## What Not To Do Yet

- do not fetch multi-year data in this planning pass
- do not run optimization
- do not change `bot/config.py` defaults
- do not mutate `.env`
- do not touch active live orders
- do not wire D.6 into runtime trading
- do not let D.5 or D.6 authorize execution
- do not promote candle-only backtest winners to live parameters

## Stop Conditions

Stop D.6 work if:

- a tool attempts a Coinbase write route
- code tries to write `state/`
- a report suggests automatic parameter application
- coverage gaps make a ticker/window comparison invalid
- fill model assumptions dominate performance
- validation shows high train performance but poor out-of-sample behavior

The correct conclusion may be "do not change parameters."
