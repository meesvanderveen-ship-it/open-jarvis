# D.6 Backlearning Architecture Roadmap v1

Timestamp: `2026-05-29T19:25:59Z`

## Purpose

D.6 is the research-only historical learning layer for the Coinbase spot LLM tradingbot. Its job is to turn local candle data, fixture evidence and report-only D.5 learning logs into defensible research artifacts.

D.6 must not trade, poll live orders, mutate trading state, change runtime configuration, optimize live parameters or feed execution automatically.

Hard gates remain:

- `research_only=true`
- `no_live_action=true`
- `no_coinbase_call=true` unless a separate bounded read-only candle fetch task explicitly authorizes public candle access
- `state_write_performed=false`
- `no_optimization=true` until a separate optimization task is explicitly approved
- `learning_to_execution_allowed=false`
- `parameter_change_allowed=false`

## Research Notes

External references inspected for architecture inspiration:

- Freqtrade backtesting docs: local OHLCV data, explicit backtest result exports, fee-aware metrics and reproducibility concerns around pairlists.
- Freqtrade hyperopt docs: parameter spaces, loss functions and repeatable random states are useful later, but optimization must remain a separate workflow.
- Hummingbot V2 strategy docs: controller/executor separation is a useful pattern for keeping signal decisions distinct from finite order-lifecycle units.
- Hummingbot executor docs: lifecycle units are finite components that manage order states under controller instructions; D.6 should model lifecycle separately from signal generation.
- vectorbt resources: dataframe/array-based signal comparison, walk-forward examples and compact metric/report workflows are useful research patterns, but no dependency is needed yet.
- Bailey and Lopez de Prado research on Deflated Sharpe Ratio and backtest overfitting: holdout alone is not enough when many trials are attempted.
- Bailey et al. Probability of Backtest Overfitting work: D.6 should track trials, out-of-sample behavior and selection bias before any parameter proposal.

Useful concepts:

- Keep data, signal generation, execution simulation, metric calculation and report packaging as separate layers.
- Treat optimization as a later explicitly-gated process, not as a hidden mode inside ordinary backtests.
- Record fees, drawdowns, trade counts, exposure, data coverage and warnings in every report.
- Prefer robust ranges and out-of-sample degradation checks over single best values.
- Include a clear `do_not_change_parameters` outcome when evidence is weak.

Rejected for now:

- importing Freqtrade, Hummingbot or vectorbt as runtime dependencies;
- full hyperopt/parameter search;
- live-controller integration;
- orderbook/trade-level fill modeling before candle-level scaffolds are stable;
- any automatic D.5 learning-to-execution bridge.

## End-State

D.6 should become a staged research pipeline:

1. Data coverage inventory.
2. Read-only candle ingest/cache with explicit bounded fetches.
3. Dataset quality scoring.
4. Baseline backtests and report bundles.
5. Level-0 signal scaffolds with fixed parameters.
6. Fee/slippage/spread assumption packs.
7. Position and exit simulation, including TP/stop/trailing placeholders.
8. Post-only maker fill realism, first from candles and later from trades/orderbook data if available.
9. Walk-forward and regime segmentation.
10. Overfitting guardrails and trial accounting.
11. Multi-ticker/timeframe research bundles.
12. D.5-compatible human review packs.
13. Separate parameter proposal workflow with tests and explicit human approval.

The final output of D.6 is evidence, not execution.

## Component Roadmap

| Stage | Component | Status | Purpose | Stop condition |
| --- | --- | --- | --- | --- |
| D.6.1 | Data Coverage Inventory | done | Define universe/timeframes/windows and dry-run chunk plans. | No bulk fetch. |
| D.6.2 | Coinbase Candle Ingest | done | Bounded read-only public candle cache. | No backtest/optimization. |
| D.6.3 | Baseline Backtest Scaffold | done | Fixed `buy_hold` and `simple_ma` reports from local candles. | No parameter search. |
| D.6.4 | Baseline Report Bundle | done | Compact JSON/Markdown summaries across candle files and baselines. | No live recommendations. |
| D.6.5 | Dataset Quality Report | proposed | Score gaps, coverage, duplicate rates, stale candles and insufficient windows. | No strategy results. |
| D.6.6 | Metrics Foundation | proposed | Standardize return, drawdown, exposure, trade, fee and warning metrics. | No new strategy. |
| D.6.7 | Walk-Forward Split Scaffold | proposed | Deterministic train/validation/test windows without optimization. | No selection/apply. |
| D.6.8 | Level-0 Signal Backtest | proposed | Fixed deterministic signal examples for research only. | No tuning. |
| D.6.9 | Fee/Slippage Assumption Pack | proposed | Compare fixed assumption scenarios without selecting winners. | No execution mapping. |
| D.6.10 | Overfitting Guardrails | proposed | Trial accounting, OOS degradation warnings and DSR/PBO-inspired placeholders. | No parameter approval. |
| D.6.11 | Research Review Pack | proposed | D.5-compatible JSONL/Markdown bundle for human Codex review. | No auto-change. |

## Backlearning Process

The safe D.6 backlearning loop is:

1. Build or verify local datasets.
2. Produce dataset quality reports.
3. Run baselines and fixed signal scaffolds.
4. Compare results across tickers, timeframes, fees and regimes.
5. Run walk-forward validation.
6. Add overfitting warnings and trial counts.
7. Export a D.5-compatible review pack.
8. Ask Codex for a separate parameter-review task.
9. If Codex proposes changes, run separate tests and require explicit human approval.
10. Apply nothing automatically.

Every review pack should allow a valid conclusion of `do_not_change_parameters`.

## Validation Standards

Before a result may be used for future parameter review, it should include:

- data coverage class per ticker/timeframe/window;
- gap count and missing-window warnings;
- fixed baseline comparison;
- fees assumption;
- trade count and minimum sample warnings;
- max drawdown and worst ticker/regime result;
- exposure/time-in-market;
- out-of-sample or walk-forward split result when available;
- trial count if multiple variants were tested;
- explicit limitations;
- safety flags proving no live action or parameter change occurred.

## Overfitting Guardrails

D.6 should fail closed or downgrade evidence when:

- a result depends on one ticker, one timeframe or one narrow regime;
- a strategy has too few trades for the window;
- train performance materially exceeds validation/test performance;
- the selected variant is only the best after many untracked trials;
- turnover is high and fee/slippage assumptions are weak;
- candle-only post-only fills would likely be unrealistic;
- coverage differs so much that ticker comparisons are unfair;
- the result cannot beat simple baselines after fees.

Later implementations can add formal metrics inspired by Deflated Sharpe Ratio and Probability of Backtest Overfitting, but v1 should first record the necessary inputs: trial count, return distribution, train/test split, selected-vs-median result and OOS degradation.

## D.5 Boundary

D.6 may emit D.5-compatible research summaries in the future, but D.5 remains report-only.

Allowed:

- export D.6 research summaries as JSON/JSONL;
- feed summaries into a separate Codex parameter-review prompt;
- propose tests or research questions.

Not allowed:

- live order polling;
- lifecycle apply;
- submit/cancel/replace/reprice;
- trading-state writes;
- runtime parameter mutation;
- learning-to-execution automation.

## Recommended Next Step

Implement `D.6 Dataset Quality Report v1` before adding more signal logic.

Rationale:

- The project already has data coverage and one cached sample.
- Baseline reports are only as reliable as the candle dataset.
- Quality scoring is small, deterministic and fixture-testable.
- It improves every later backtest, walk-forward split and review pack.

Acceptance criteria for that task:

- read local normalized candle files only;
- refuse `state/` and `.env` paths;
- report coverage span, candle count, duplicate count if available, gap count, expected-vs-observed count, first/last candle and quality class;
- emit safety flags;
- provide CLI stdout and optional explicit report output;
- use fixture tests and no Coinbase calls.

## Stop Condition

Stop after this roadmap. Do not proceed into Level-0 signals, parameter search, optimization, new Coinbase fetching, live monitoring, lifecycle apply, cancel/replace/reprice or service operations from this task.
