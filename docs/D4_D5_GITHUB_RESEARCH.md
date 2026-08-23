# D.4 / D.5 GitHub Research Spike

Timestamp: `2026-05-29`

Scope: research + design notes only. No Coinbase calls, no live action, no cancel, no replace, no submit, no lifecycle apply, no trading-state write, no service restart, no `.env` mutation, no dependency changes and no external code copy.

Active context:
- Active D.3 TP1 SELL remains `BTC-USDC` at `84800.00`, branch `OPEN/open keep_open`, zero fills.
- Operator decision remains keep current TP1 / wait.
- D.3 lifecycle offline test strategy is in `docs/D3_EXIT_LIFECYCLE_TEST_STRATEGY.md`; focused D.3 lifecycle pytest set was green with `98 passed`.

## Source Matrix

| Project | URL | License | Relevant component | Useful pattern | Failure mode | Applicability | Copy/license risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Freqtrade | https://github.com/freqtrade/freqtrade and https://docs.freqtrade.io/en/latest/stoploss/ | GPL-3.0 | trailing stoploss, stoploss-on-exchange, backtesting, protections | trailing stop has static initial stop, highest-price tracking, positive offset activation, optional offset-only activation | whipsaw exits, ROI/trailing precedence confusion, backtest assumptions differ from live | High for D.4 design semantics and D.5 test cases | High: GPL-3.0. Use concepts only; do not copy code |
| Freqtrade protections | https://www.freqtrade.io/en/2024.1/includes/protections/ | GPL-3.0 | StoplossGuard, CooldownPeriod | cooldown after exits and stoploss burst guard | repeated loss exits, retry-storm behavior, overtrading immediately after close | High for D.4 cooldown and D.5 safety metrics | High: GPL-3.0. Reimplement local concepts |
| Freqtrade backtesting | https://docs.freqtrade.io/en/stable/backtesting/ | GPL-3.0 docs/project | trailing stop backtest assumptions, exported trade analysis | explicit intra-candle ordering assumptions and exported trades for analysis | false confidence from no slippage or candle ordering; historic product-rule mismatch | High for D.5 no-fill/fill quality test design | High: GPL-3.0. Do not copy implementation |
| CCXT | https://github.com/ccxt/ccxt and https://github.com/ccxt/ccxt/wiki/manual | MIT | exchange order API abstraction | exchange capability checks, `fetchOpenOrder(s)`, `fetchOrder(s)`, `fetchMyTrades`, `createOrder`, `cancelOrder` | cancel ambiguity, unsupported order history, local userland cache required | Medium/high for D.4 exchange-neutral vocabulary and failure tests | Low/moderate: MIT, but no dependency added in this round |
| OctoBot | https://github.com/Drakkar-Software/OctoBot | GPL-3.0 | full open-source bot with AI, grid, DCA, TradingView, open orders/profit UI | full lifecycle UI and portfolio/open-order tracking | broad feature surface, plugin complexity, GPL contamination | Medium for product workflow and observability ideas | High: GPL-3.0. Concepts only |
| OctoBot docs/indexed changelog references | https://docfork.com/drakkar-software/octobot | GPL-3.0 | trailing stop orders, trading modes, order issues | track known order edge cases in release notes | stop losses not created after instantly filled limit orders | Medium for failure-mode checklist | High: third-party index plus GPL source; verify against upstream before relying |
| Hummingbot | https://github.com/hummingbot/hummingbot | Apache-2.0 | high-frequency bot, connectors, strategies | event-driven order tracking and strategy-level metrics | connector event gaps can corrupt strategy state | High for architecture patterns; medium for direct D.4 | Moderate/low: Apache-2.0, but no code copy |
| Hummingbot order refresh tolerance | https://hummingbot.org/strategies/v1-strategies/strategy-configs/order-refresh-tolerance/ | Apache-2.0 project/docs | cancel/replace refresh gating | tolerate small spread/mid-price changes to avoid unnecessary cancel/replace | cancel churn, queue-priority loss, negative-spread risk if tolerance too broad | High for D.4 cancel-first preview thresholds | Moderate/low: concept only |
| Hummingbot performance history | https://hummingbot.org/client/history/ | Apache-2.0 project/docs | local trade CSV, P&L, fee-aware performance | persist local trades and compute avg price, hold value, current value, trade P&L, total P&L, return | incomplete local history after restart; confusing live vs history return | High for D.5 metrics scaffold | Moderate/low |
| Hummingbot order lifecycle docs | https://hummingbot.org/developers/connectors/architecture/order_lifecycle/ | Apache-2.0 project/docs | order created/fill/completed/cancelled/expired/failure events | explicit order events: created, filled, completed, cancelled, expired, failed | events out of order or missing; DEX/block-delay fills after cancellation | High for D.3/D.4 event model tests | Moderate/low |
| Jesse | https://github.com/jesse-ai/jesse and https://jesse.trade/help/faq/does-jesse-support-trailing-stop-loss-or-some-kind-of-break-even-functionality | MIT | strategy framework, smart ordering, update_position, ML pipeline | strategy updates stop-loss dynamically; metrics, benchmark, Monte Carlo, labelled ML gather/train/deploy | learning overfit; smart ordering hides exchange-specific order details | Medium for D.5 metrics/ML staging ideas | Low/moderate: MIT; still no code copy |
| Superalgos | https://github.com/Superalgos/Superalgos | Apache-2.0 | visual strategy design, data mining, backtesting, paper/live trading | separate design/test/deploy workflow and visual postmortem | high platform complexity, dependency/runtime footprint | Medium for product workflow and D.5 analysis UI ideas | Moderate/low: Apache-2.0, no dependency |
| vectorbt | https://github.com/polakowo/vectorbt | Apache-2.0 with Commons Clause | vectorized backtesting and metrics | large-scale parameter sweeps and trade metrics | fair-code/commercial restriction; not an execution engine | Low/medium for D.5 offline analysis concepts | High for adoption because Commons Clause; avoid dependency and code copy |

## Key D.4 Patterns

1. Separate trailing signal from exchange write.
   - Freqtrade treats trailing as a stop price that only moves in the favorable direction after activation.
   - For this bot, D.4 should first produce a read-only `trailing_preview` containing activation state, peak/reference price, proposed stop/exit price, product-rule quantization and explicit `would_cancel_replace=false/true`.

2. Activation threshold before trailing.
   - Use `activation_pct` or plan-aware activation instead of trailing immediately.
   - For the current D.2/D.3 shape, activation should not compete with the live TP1 while `OPEN/open keep_open` remains active.

3. Stop only moves toward less risk.
   - For a long spot position, trailing stop/exit reference should never move down once activated.
   - Tests should cover peak increase, price decline, same-price no-op and product increment rounding.

4. Cancel-first replacement.
   - D.4 must keep the D.3 invariant: no replacement SELL before confirmed terminal/cancel evidence for the old order.
   - CCXT and Hummingbot both imply that exchange order state can be incomplete or exchange-specific, so local state must wait for confirmed evidence.

5. Refresh tolerance and cooldown.
   - Hummingbot's order refresh tolerance is directly relevant: avoid cancel/replace churn when the improved price is inside a tolerance band.
   - Freqtrade protections add cooldown and stoploss guard ideas: after a failed replace, reject, repeated no-fill or loss exit, D.4 should pause rather than retry.

6. Product-rule and liquidity gates.
   - Every proposed replacement must check base increment, price increment, min quote, min base, post-only/non-crossing safety and estimated quote.
   - A maker replacement can become taker if the book moves; D.4 preview must state the book evidence timestamp and stale-book cutoff.

7. Observability before automation.
   - Required preview fields: lifecycle order id, linked position id, current reservation, open D.3 exit count, activation state, peak price, trailing distance, proposed price, reason, blockers, warnings, next forbidden actions.

## Key D.5 Patterns

1. Learn from completed lifecycle events only.
   - D.5 should reject incomplete D.3/D.4 events. `OPEN/open keep_open`, partial-only events and uncertain cancel/replace attempts are not valid training examples.

2. Persist local execution facts.
   - Hummingbot's local trade history model suggests storing durable rows for fill quality, average price, fees, P&L and return.
   - For this bot, add analysis-only metrics over existing order/state/audit logs before any model or policy influences execution.

3. Metrics before ML.
   - Recommended metrics: slippage to decision mid, slippage to book best bid/ask, fill latency, no-fill age, cancel latency, replace success rate, reject rate, partial-fill delta count, fee-adjusted edge, realized vs planned exit price, stale-book age.

4. Guard against learning-to-execution leakage.
   - Jesse's ML pipeline is useful as a staged model: gather, train, deploy. For this bot, keep only gather/report initially.
   - Any future `learning-to-execution` path needs a separate feature flag, dry-run comparison window, explicit ACK and rollback rule.

5. No-fill is a first-class outcome.
   - The current TP1 is far above market, so no-fill duration and opportunity cost should be measured without forcing action.
   - D.5 should distinguish planned swing target no-fill from failed near-market execution.

6. Backtest assumptions must be explicit.
   - Freqtrade documents important assumptions around trailing and intra-candle order. D.5 should record assumptions in reports and avoid using candle-only tests to claim live execution safety.

## Failure Modes To Test

| Area | Failure mode | Test idea |
| --- | --- | --- |
| trailing activation | activates before threshold | fake price path below threshold; assert no proposed cancel/replace |
| trailing monotonicity | stop decreases after price drop | fake peak then decline; assert trailing stop unchanged |
| product rules | replacement below min quote/base | quantized candidate below min; assert blocked |
| post-only | candidate crosses book after stale quote | stale book timestamp or best bid moves above candidate; assert blocked |
| cancel-first | replacement submit attempted before cancel confirmation | fake client records calls; assert no replace until confirmed cancel |
| cancel uncertainty | cancel returns pending/empty success | assert no replace and manual review |
| cooldown | repeated failed replace attempts | assert cooldown blocker and no retry-storm |
| reservation | partial fill leaves stale reserved base | assert reservation equals remaining open exit size |
| duplicate | two open D.4 exits for one logical position | assert P0 block |
| no-fill | old order remains open beyond threshold | report no-fill age; no action unless operator approves |
| slippage | fill worse than decision reference | metric only; no automatic policy change |
| learning leakage | D.5 result changes execution parameters | assert report-only mode and `learning-to-execution` blocked |

## Recommended D.4 Route

recommended D.4:
1. Build `D.4 Trailing Preview Scaffold` only.
2. Inputs: local position/order snapshot, read-only market snapshot fixture, D.2 plan metadata, product rules fixture.
3. Outputs: activation state, peak/reference price, trailing distance, proposed replacement candidate, blockers, warnings, no-live-action proof.
4. Tests first:
   - `test_d4_trailing_preview_never_submits_and_respects_product_rules`
   - `test_d4_trailing_stop_only_moves_up_after_activation`
   - `test_d4_cancel_replace_candidate_requires_cancel_first_and_ack`
   - `test_d4_cooldown_blocks_retry_storm_after_failed_replace`
5. Do not connect it to live cancel/replace while the active D.3 TP1 is `OPEN/open keep_open`.

## Recommended D.5 Route

recommended D.5:
1. Build `D.5 Execution Metrics Scaffold` as analysis-only reports.
2. Inputs: temp or read-only copies of order events, lifecycle evidence, D.2/D.3 plan fields and market snapshots.
3. Metrics: fill quality, slippage, no-fill duration, cancel/replace latency, fee-adjusted realized edge, reject/cancel/partial rates.
4. Tests first:
   - `test_d5_metrics_require_terminal_or_completed_fill_lifecycle`
   - `test_d5_no_fill_metric_does_not_trigger_execution_change`
   - `test_d5_learning_to_execution_gate_blocks_without_explicit_ack`
   - `test_d5_slippage_report_handles_missing_book_snapshot`
5. Keep learning report-only until there are enough complete lifecycle events and a separate operator-approved execution gate.

## License And Copy Policy

- GPL-3.0 projects such as Freqtrade and OctoBot are useful for behavior patterns, failure modes and tests only. Do not copy implementation or structure.
- Apache-2.0 and MIT sources are lower risk, but this round still adds no dependency and copies no code.
- vectorbt's Commons Clause means avoid adoption as a dependency unless there is a separate legal/product decision.
- All implementation should be native to this repo's D.3 safety model: ACK gates, temp-dir tests, fake clients, no live action by default.

## Stop Condition

This spike is complete when this document is linked from `docs/CODEX_PROJECT_CONTEXT.md`, prompt templates include D.4/D.5 research/scaffold prompts and validation `rg` passes. Stop with no Coinbase poll, no live action and no trading-state write.
