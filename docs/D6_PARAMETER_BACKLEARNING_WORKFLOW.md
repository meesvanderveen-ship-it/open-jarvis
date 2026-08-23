# D.6 / D.5 Parameter Backlearning Workflow

Timestamp: `2026-05-30T23:28:53Z`

## Purpose

D.6 and D.5 backlearning are research/report-only layers. They identify parameters that may eventually deserve human review, describe how evidence should be gathered, and package warnings and limitations. They must not trade, mutate runtime configuration, touch live orders, write `state/`, rewrite prompts for live use, or connect learning directly to execution.

Default conclusion for every report is: `parameter_review_approved=false`.

## Current State

Existing D.6 layers:

- data coverage inventory and coverage classes;
- bounded candle ingest/cache design;
- dataset quality report and aggregate;
- fixed baseline backtest and bundle reports;
- metrics foundation;
- fee/slippage/cost assumption packs;
- walk-forward split scaffold;
- fixed Level-0 signal backtest and bundle;
- cost-aware split baseline reports;
- research review pack;
- overfitting/trial-accounting guardrails;
- out-of-sample degradation checks.

Existing D.5 layers:

- execution metrics scaffold for fill/no-fill/latency/slippage/fees;
- structured learning log schema and exporter;
- D.45 historical/operator reports that can feed report-only learning events;
- trade reflection memory with coarse anti-overfit warnings.

Missing pieces for serious backlearning:

- a single parameter map that categorizes every candidate parameter family;
- category-specific evidence requirements and blockers;
- a formal human review workflow before config mutation;
- stronger fill realism and post-only queue assumptions;
- D.5 execution-outcome adapter into D.6 evidence packs;
- regime segmentation and formal sample-size gates before parameter proposals.

## Research Notes

Sources inspected for ideas:

- Freqtrade hyperopt/backtesting docs: parameter spaces, objective/loss functions, separate search spaces, and the risk of automatically exporting optimized values.
- Hummingbot V2 controller/executor docs: controller/executor separation and finite order-lifecycle components.
- vectorbt optimization examples: compact array-style research, parameter grids and walk-forward reporting ideas.
- Bailey and Lopez de Prado, Deflated Sharpe Ratio and backtest-overfitting work: trial counts, selection bias, non-normal returns and OOS degradation matter before trusting a backtest.

Useful concepts:

- separate data, signals, execution simulation, metrics and review packaging;
- track trial counts even before formal optimization exists;
- compare against simple baselines after fees and slippage;
- require walk-forward and regime breadth before any proposal;
- allow `do_not_change_parameters` as a valid outcome.

Rejected concepts for this repo now:

- importing Freqtrade, Hummingbot or vectorbt as dependencies;
- hyperopt/parameter search inside ordinary reports;
- automatic parameter export;
- direct learning-to-execution;
- prompt rewriting or AI threshold mutation from research logs.

Risks:

- candle-only fills can overstate post-only execution quality;
- small crypto samples can overfit one ticker/listing regime;
- D.5 logs can be anecdotal until enough terminal events exist;
- AI/prompt parameters are especially high-risk because they affect reasoning and safety gates indirectly.

## Parameter Map

### A. Universe / Market Selection

Candidates:

- `allowed_tickers`;
- ticker inclusion/exclusion and liquidity tiers;
- timeframes `15M`, `1H`, `4H`, `1D`;
- primary research horizon `3 years`;
- extended regime/stress horizon `5 years`;
- newer-asset coverage-limited handling;
- coverage class thresholds: `full_5y`, `full_3y`, `partial`, `insufficient`.

Never automatic:

- live allowlists for actual trading;
- delisting/cancel-only handling;
- any rule that expands live universe without human review.

### B. Market-Data / Feature Parameters

Candidates:

- EMA/SMA windows: `20`, `50`, `200`, fixed D.6 `5/20` scaffold;
- RSI period `14`, oversold/overbought thresholds;
- ADX period `14`, strength thresholds such as `25`;
- Bollinger period/std: `20`, `2.0`, compression threshold `0.05`;
- Donchian lookbacks: `20`, `55`;
- volume-vs-average windows and thresholds;
- volatility/compression thresholds;
- spread filters and `max_spread_pct`;
- orderbook depth imbalance and pressure thresholds;
- regime filters from `4H`/`1D` trend, BTC/ETH context, breadth and sentiment.

Never automatic:

- feature changes that silently alter live judge payloads;
- live orderbook polling frequency;
- private account/order data access for research.

### C. Gatekeeper / Analysis Routing

Candidates:

- reject/watch/analyze thresholds;
- `judge_min_gate_confidence`, `judge_min_synth_confidence`, `judge_min_bull_score`, `judge_max_bear_score`;
- max candidates for deep analysis/gate;
- priority-analyze triggers;
- liquidity/spread conditions;
- `cooldown_minutes`;
- pending intent TTL, min confidence, trigger score and max chase distance;
- duplicate intent suppression tolerance.

Never automatic:

- final judge authority;
- ACK strings;
- live execution flags;
- API/model secrets;
- automatic promotion from research evidence into execution.

### D. Entry Signal Parameters

Candidates:

- trend-following thresholds;
- breakout lookbacks and Donchian proximity;
- mean-reversion RSI/Bollinger thresholds;
- pullback/reclaim triggers;
- confirmation candle rules;
- volume confirmation;
- regime alignment requirements;
- invalidation distance and ATR buffers;
- no-trade regime definitions.

Never automatic:

- direct entry permission;
- bypasses for final judge, deterministic risk rails or live submit gates.

### E. Position Sizing / Risk Parameters

Candidates:

- `default_quote_size_usdc`;
- `max_notional_usd`;
- `max_open_positions`;
- ticker/portfolio exposure caps;
- volatility-adjusted sizing;
- `max_daily_loss_usdc`;
- minimum expected net edge;
- fee/spread/slippage safety buffer;
- risk score thresholds.

Never automatic:

- live size increases;
- daily loss guard weakening;
- exposure cap expansion;
- averaging-down enablement.

### F. D.2 Position Executor Parameters

Candidates:

- initial stop/invalidation fallback;
- TP1 and TP2 target distances;
- runner allocation;
- TP1/TP2/RUNNER or TP_CLOSE split sizing;
- `phase_d2_default_time_limit_hours`;
- trailing activation and distance defaults;
- add-to-winner limits;
- no-averaging-down rule;
- small-position fallback logic;
- fee-aware min net edge, reward-to-fee and reward-to-risk ratios;
- spread/slippage/fee model.

Never automatic:

- enabling averaging down;
- weakening no-oversell constraints;
- converting preview-only exit intents into live orders.

### G. D.3 Controlled Exit Parameters

Candidates:

- reduce-only-local reservation rules;
- max open exit orders;
- max new exit orders per cycle;
- exit order quote cap;
- post-only default;
- min base/quote handling;
- base/price increment rounding;
- duplicate-exit prevention;
- partial-fill handling;
- terminal lifecycle closeout rules;
- apply-preview vs apply boundary.

Never automatic:

- live submit/cancel/replace;
- lifecycle apply;
- reservation repair;
- duplicate/oversell tolerance;
- ACK requirements.

### H. D.4 Dynamic Order Management

Candidates:

- stale order age threshold;
- cancel/replace trigger and reprice threshold;
- refresh tolerance;
- trailing activation threshold;
- trailing stop distance;
- monotonic trailing behavior;
- cancel-first requirement;
- cooldown after failed replace;
- post-only crossing guard;
- no-fill duration thresholds;
- near-market de-risk vs swing-target distinction.

Never automatic:

- removing cancel-first confirmation;
- replacement before terminal cancel evidence;
- retry loops;
- near-market loss exits without explicit human choice.

### I. D.5 Execution Learning Metrics

Candidates:

- fill rate;
- no-fill duration;
- missed-fill / correct-no-fill / avoided-bad-fill labels;
- maker/taker/liquidity classification;
- slippage vs decision mid and best bid/ask;
- fee-adjusted realized edge;
- MFE/MAE;
- partial-fill rate;
- cancel/replace latency;
- order age until fill/cancel;
- reject rate;
- reservation drift;
- duplicate/oversell incidents;
- realized vs planned TP/stop/runner outcome.

Never automatic:

- using metrics as execution approval;
- hiding P0 incidents inside aggregate statistics;
- training on incomplete `OPEN/open` observations as terminal outcomes.

### J. AI / Prompt / Judge Parameters

Candidates:

- analyst weights;
- confidence cutoffs;
- final judge approval threshold;
- debate/synth thresholds;
- reasoning-quality gates;
- `must_reject_if` criteria;
- schema strictness;
- model selection by task complexity;
- prompt-output hygiene thresholds.

High-risk boundary:

- D.6 may report evidence only.
- No prompt rewrite, model switch, judge-threshold mutation or schema loosening may occur without separate human review, tests and a config/prompt-change task.

Never automatic:

- model credentials;
- model routing for live decisions;
- final judge approval semantics;
- prompt text used in live trading.

## Category Workflow

For every category, use the same five-stage evidence pattern.

1. Evidence source:
   - local normalized candles;
   - cached orderbook snapshots when explicitly available;
   - D.5 execution logs;
   - lifecycle events;
   - decision outcomes;
   - trade reflections;
   - fixtures.

2. Research method:
   - baseline comparison;
   - fixed signal scaffold;
   - walk-forward validation;
   - regime segmentation;
   - cost sensitivity;
   - fill realism sensitivity;
   - no-fill analysis;
   - execution outcome attribution.

3. Metrics:
   - net return, max drawdown, exposure, trade count;
   - win/loss and average return;
   - fee/slippage-adjusted return;
   - fill quality and no-fill rate;
   - OOS degradation;
   - stability by regime;
   - trial count;
   - warning/blocker count.

4. Validation:
   - dataset quality must pass;
   - train/validation/test split;
   - walk-forward where relevant;
   - multiple tickers and timeframes;
   - explicit cost scenarios;
   - holdout not reused;
   - out-of-sample degradation check;
   - trial-accounting guardrail;
   - no promotion from one ticker, one regime or one small sample.

5. Output:
   - evidence pack;
   - warning pack;
   - valid `do_not_change_parameters` conclusion;
   - optional parameter proposal draft;
   - human review required;
   - `parameter_review_approved=false` by default.

## Category-Specific Gates

| Category | Data source | Report type | Metrics | Change blockers |
| --- | --- | --- | --- | --- |
| Universe | coverage inventory, candle cache | coverage/eligibility pack | available years, gaps, volume/spread proxy | insufficient coverage, unfair ticker comparison |
| Features | candles, quality reports | feature stability pack | hit rate, regime stability, OOS degradation | one timeframe/ticker, unstable thresholds |
| Gatekeeper | historical decisions, fixtures, candles | routing calibration pack | false reject/watch/analyze, later move outcome | weak labels, hindsight leakage |
| Entry | candles, fixed signals | signal evidence pack | net return, drawdown, trade count, costs | cannot beat baseline after costs |
| Sizing/risk | backtest equity curves | sizing sensitivity pack | drawdown, exposure, loss tails | size hides weak signal, risk cap weakening |
| D.2 | plans, candles, cost scenarios | exit-plan pack | TP/stop outcomes, edge, fallback frequency | min-size artifacts, poor fee realism |
| D.3 | lifecycle fixtures/logs | controlled-exit safety pack | duplicate/oversell, reservation drift, partials | any P0 incident or incomplete lifecycle |
| D.4 | market paths, D.5 logs | order-management pack | no-fill age, reprice outcome, latency | cancel uncertainty, churn, stale book |
| D.5 | execution metrics/logs | execution learning pack | slippage, fees, fill/no-fill quality | too few terminal examples |
| AI/prompt | archived decisions/reflections | prompt review pack | schema failures, outcome buckets | anecdotal evidence, safety-gate impact |

## Evidence Flow

1. Historical candles enter D.6 ingest/cache.
2. Dataset quality reports classify coverage, gaps, duplicates and freshness.
3. Baselines establish buy-hold and fixed signal references.
4. Walk-forward splits create train/validation/test evidence.
5. Regime segmentation separates trend, chop, volatility and stress contexts.
6. Cost assumptions add fee, spread and slippage scenarios.
7. Fill realism models post-only, no-fill and queue assumptions separately from signal edge.
8. D.5 execution logs add live/paper lifecycle facts: fills, no-fills, cancels, rejects, slippage and fees.
9. Trade reflection adds coarse repeated-context evidence with anti-overfit labels.
10. D.6 review pack merges evidence, warnings, blockers and prohibited interpretations.
11. Human receives a review pack with no automatic approval.

## Full Pipeline

1. Data coverage inventory.
2. Candle ingest/cache.
3. Dataset quality report.
4. Dataset quality aggregation.
5. Walk-forward splits.
6. Metrics foundation.
7. Fee/slippage assumptions.
8. Baseline reports.
9. Fixed signal scaffolds.
10. Cost-aware baseline/signal reports.
11. Research review pack.
12. Overfitting/trial-accounting guardrails.
13. Out-of-sample degradation checks.
14. Regime segmentation.
15. Fill realism / post-only queue assumptions.
16. D.5 execution metrics ingestion.
17. Trade reflection evidence.
18. Parameter sensitivity reports.
19. Human review pack.
20. Parameter proposal draft.
21. Separate parameter-change task.
22. Observe-only/shadow validation.
23. Controlled live validation only after explicit approval.

## Overfitting And Leakage Gates

D.6 must fail closed or downgrade evidence when:

- dataset quality is incomplete;
- coverage differs materially across tickers;
- sample size is too small;
- one ticker/timeframe/regime drives the result;
- train performance materially exceeds validation/test;
- holdout was reused;
- trial count is missing;
- costs or slippage erase edge;
- candle-only fills are unrealistic;
- D.5 examples are incomplete or anecdotal;
- the proposal weakens P0/P1 safety.

Learning-to-execution is always blocked:

- `learning_to_execution_allowed=false`;
- `parameter_change_allowed=false`;
- `runtime_config_mutation_allowed=false`;
- `strategy_parameter_mutation_allowed=false`;
- `parameter_review_approved=false`.

## Manual Promotion Workflow

No parameter proposal may become a runtime config change until all steps are complete:

1. Separate Codex parameter-review prompt.
2. Reproducible research report with exact inputs and command lines.
3. Tests for report generation and safety flags.
4. Human review of evidence, warnings and limitations.
5. Explicit approval for the proposed parameter change.
6. Separate config-change task.
7. Focused tests for the config change.
8. Observe-only/shadow validation.
9. Separate live-use approval if live behavior is affected.

The proposal must be rejected if it:

- relies on single-sample evidence;
- weakens live gates, ACKs or P0 protections;
- mutates `.env` or runtime config in the research task;
- uses D.5 learning as execution permission;
- lacks an easy rollback or shadow-validation plan.

## Options Considered

| Option | Value | Risk | Size | Testability | Live-safety isolation | Future-review help | Premature-optimization risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D.6 Parameter Map / Backlearning Workflow Doc v1 | high | low | small | docs checks | high | high | low |
| D.6 Parameter Candidate Inventory Tool v1 | high | medium | medium | high | high | high | medium |
| D.5 Execution Outcome -> D.6 Evidence Adapter v1 | high | medium | medium | high | high | high | low/medium |
| D.6 Regime Segmentation Scaffold v1 | medium/high | medium | medium | high | high | high | medium |
| D.6 Fill Realism / Post-Only Assumption Pack v1 | high | medium | medium | high | high | high | medium |
| D.6 Parameter Review Pack Scaffold v1 | medium | medium | medium | high | high | high | medium |

Chosen step: `D.6 Parameter Map / Backlearning Workflow Doc v1`.

Rationale: no dedicated parameter-map document existed; this step clarifies scope, evidence flow and hard gates without optimization, parameter search, data fetches or runtime changes.

## Next Recommended Step

Implement `D.6 Parameter Candidate Inventory Tool v1` as a stdout/report-only scanner over local code/docs that lists parameter names, defaults, source files and category tags. It must not rank parameters, search values or propose changes.

## Stop Condition

Stop after this research-only workflow document and project checkpoint. Do not continue into optimization, parameter search, parameter review approval, config changes, prompt changes, Coinbase fetching, live trading, lifecycle apply, cancel/replace/reprice or service operations.
