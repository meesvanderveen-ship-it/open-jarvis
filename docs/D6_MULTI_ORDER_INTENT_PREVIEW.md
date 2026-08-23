# D.6 Multi-Order Intent Preview

`bot/phase_d6_multi_order_intent_preview.py` is a report-only intent design layer. It evaluates local bot outputs, setup context and local state snapshots, then emits structured order intents, near-miss candidates and rejected-candidate reasons.

It does not call Coinbase, submit/cancel/replace orders, place market orders, execute SELLs, mutate `.env`, mutate config, write `state/`, bypass `approve_trade`, enable replication or connect learning to execution.

## Policy

- preview-only by default.
- maximum 5 open orders total.
- maximum 20 USDC per order.
- maximum 100 USDC total quote reserved for pending/open BUY orders.
- maximum 1 open order per ticker.
- maximum 2 new orders per cycle.
- maker/limit intent is preferred.
- market orders are represented but disabled by default and future-ACK gated.
- SELL intents are represented but live SELL remains disabled and future-ACK gated.

## Candidate Calibration

A forming BUY setup is calibrated before full `approve_trade`. The layer distinguishes:

- hard blockers: explicit reject/blocked decisions, do-not-chase violations, spread/orderbook policy failures, min-notional/cap failures, market-order policy, SELL safety, duplicate exit and no-oversell failures.
- missing-data blockers: missing ticker, proposed price, invalidation reference or target reference.
- soft blockers: weak confidence, unclear setup family, weak volume/momentum in non-breakout contexts, low edge score or low reward/risk.
- near-miss intents: candidates with useful structure and only limited soft blockers. These are review-only and not accepted as final preview-ready intents.
- preview-ready intents: candidates with no hard blockers, no missing-data blockers and no soft blockers. These still have `live_submit_eligibility=false`.

Ordinary entry-gate `watch`, `analyze` or `wait` decisions are preview context, not hard rejection by default. Explicit reject/blocked/no-trade decisions remain hard blockers.

Known setup families include `trend_continuation`, `reclaim_reversal`, `mean_reversion`, `breakout`, `range_reclaim`, `support_retest` and `pullback_continuation`. If a candidate says `unclear`, the preview layer tries to infer setup family from entry-gate setup, analysis setup, strategy, reasons, trade-plan labels and level context. If it cannot infer a setup, it emits `setup_family_unclear` as a soft blocker instead of the old automatic `no_recognizable_pattern_setup` hard-style rejection.

Volume/momentum is hard only for clear dead-volume plus adverse confirmation, momentum-dependent breakout/reclaim cases without confirmation, weak orderbook combinations or missing structure. Otherwise `bad_volume_or_momentum` is a soft blocker that can produce a near-miss.

A forming BUY setup still needs enough confidence, price near a valid level, acceptable spread, acceptable orderbook pressure, invalidation, target/reward reference, no do-not-chase violation, no open-order conflict and enough quote/min-notional room.

SELL previews require available linked/base balance after reservations, no oversell, no duplicate open SELL/exit for the ticker, a defined TP/SL/trailing/emergency reason in future integrations and explicit future ACK before any execution path.

## Reports

Run:

```bash
python3 tools/build_d6_multi_order_intent_preview.py \
  --json-out reports/d6/d6-multi-order-intent-preview-YYYYMMDD.json \
  --markdown-out reports/d6/d6-multi-order-intent-preview-YYYYMMDD.md
```

The report includes safety flags, `preview_only=true`, total candidates, preview-ready count, near-miss count, hard-rejected count, rejected count, top preview-ready intents, top near-miss intents, top hard blockers, top soft blockers, BTC-USDC explanation when present, reservation summary, risk summary, warnings and the next safe operator decision.

## Live Boundary

This layer is not wired into the autonomous live loop. A future sprint may add a default-off, ACK-gated dry-run adapter into the existing strict Phase-C guard. Actual submit, market order support or SELL/exit execution require separate review, tests, exact operator ACK and unchanged P0 protections.
