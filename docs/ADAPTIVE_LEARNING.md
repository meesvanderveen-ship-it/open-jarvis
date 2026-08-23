# Adaptive learning intelligence

This document describes the adaptive learning intelligence sprint added on
top of the existing GrowBot/River learning layer (see
[`docs/GROWBOT_RIVER_LEARNING_INTEGRATION.md`](GROWBOT_RIVER_LEARNING_INTEGRATION.md)
and [`docs/AUTONOMOUS_PARAMETER_GOVERNOR.md`](AUTONOMOUS_PARAMETER_GOVERNOR.md)
for the full pipeline those two documents already cover).

**GrowBot/River remains the source of truth for the learning layer.** This
sprint does not replace it, does not introduce a second/parallel learning
system, and does not add any new apply-route. It only adds depth,
explainability and overfit-risk scoring on top of evidence GrowBot/River and
the existing outcome trackers already produce, and presents it on the
dashboard.

```text
raw bot events / decisions / outcomes
  -> existing GrowBot learning adapter (bot/growbot_learning_adapter.py)
  -> existing River online learner / sidecar (bot/river_online_parameter_learner.py)
  -> existing GrowBot/River readiness + proposal evidence
     (bot/growbot_river_readiness.py, reports/growbot_river/)
  -> adaptive learning intelligence / proposal funnel / dashboard layer (this sprint)
  -> unchanged governance / approved-profile route (the only apply path)
```

## What this sprint added

| Module | Purpose |
|---|---|
| `bot/overfit_risk_model.py` | Regime/ticker coverage, time-split direction stability, overfit-risk scoring (`low`/`medium`/`high`). |
| `bot/parameter_proposal_scoring.py` | Six-tier proposal maturity ladder and a composite `proposal_score`. `apply_ready_candidate` is intentionally unreachable from this module. |
| `bot/adaptive_learning_intelligence.py` | Per-parameter evidence aggregator. Reads `state/decision_outcomes.json`, `logs/execution_outcomes.jsonl`, `state/trade_reflections.jsonl`, `state/opportunity_memory.json` -- and cross-checks every mapped parameter against the existing GrowBot/River learning-cycle report (`reports/growbot_river/growbot-river-learning-latest.json`). Also builds wait-decision-quality and missed-opportunity-learning stats. |
| `bot/regime_parameter_profiles.py` | Same evidence, segmented per canonical regime (`trend_up`/`trend_down`/`range_chop`/`high_volatility`/`low_volatility`/`drawdown_risk_off`). Report-only, never activated. |

All four modules are pure read-and-aggregate: no LLM calls, no Coinbase
calls, no state writes, no `.env` changes, no parameter mutation.

## GrowBot/River is the primary source, not a peer system

`bot/adaptive_learning_intelligence.py` loads the real GrowBot/River
learning-cycle output (`reports/growbot_river/growbot-river-learning-latest.json`,
produced by `tools/run_growbot_river_learning_cycle.py`) and, for every
parameter that report already has an opinion on, surfaces that opinion
verbatim instead of recomputing a competing number:

- `river_backend` -- `"native_sidecar"` when the real River package answered
  (`river.backend.river_available is True`), else `"report_only"` (the
  deterministic fallback described in
  [`docs/GROWBOT_RIVER_LEARNING_INTEGRATION.md`](GROWBOT_RIVER_LEARNING_INTEGRATION.md)).
- `source` -- always `"growbot_river"`.
- `growbot_river_cross_check` (per parameter) -- whether GrowBot/River's own
  `river.parameter_signals`/`proposals`/`blocked_proposals` already cover this
  parameter, and if so its confidence, direction, evidence count and (when
  blocked) the real blocker text. When GrowBot/River has already blocked a
  candidate (e.g. `direction_not_stable_across_prior_learning_cycles`), that
  blocker text drives this layer's `why_no_proposal`, instead of a separately
  invented reason.

Where GrowBot/River has not yet produced a signal for a parameter (today:
the two execution-outcome-only parameters,
`ORDERBOOK_ENTRY_MAX_DISTANCE_FROM_MID_PCT` and
`EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT`), this layer's own per-vote evidence
analysis is the only thing available -- that is reported as an honest data
gap (`river_signal_available: false`), not hidden behind a synthetic number.

## Proposal tiers

`bot/parameter_proposal_scoring.py` defines a six-tier maturity ladder,
weakest to strongest evidence:

```text
observed_signal           some evidence exists, not yet a directional candidate
shadow_candidate          a stable direction with a minimum evidence floor
backtest_candidate        enough volume and regime spread for a historical-replay check
walk_forward_candidate    direction holds across an out-of-time split and >1 ticker
operator_review_candidate everything above, plus low overfit risk and a high score
apply_ready_candidate     intentionally unreachable from this layer
```

`apply_ready_candidate` is never assigned by `classify_tier()`. This learning
layer never decides a parameter is ready to apply -- that decision stays with
`autonomous_parameter_governor` + `approved_parameter_profile`
(`docs/AUTONOMOUS_PARAMETER_GOVERNOR.md`).

## Overfit-risk model

`bot/overfit_risk_model.py` scores how likely a piece of evidence is to be
overfit to one ticker, one regime, or one short time window, combining:

- evidence count (volume floor before any tier beyond `observed_signal`)
- regime coverage (how many of the 6 canonical regimes have evidence)
- ticker coverage (how concentrated the evidence is in one ticker)
- direction stability (does the signal agree across an earlier/later
  chronological split, not just in aggregate)
- effect size (mean absolute observed effect, not just a vote count)
- live relevance (recency decay -- old evidence counts for less)

Single-regime or single-ticker-dominated evidence is explicitly penalized
(`evidence_concentrated_in_a_single_market_regime`,
`single_ticker_dominance_*`), and the resulting `low`/`medium`/`high` risk
label feeds directly into the proposal tier and score -- a high-confidence
signal from one ticker in one regime cannot reach `operator_review_candidate`
on its own.

**Known data-quality finding (not a bug in this sprint):** on the live
`state/decision_outcomes.json`, the large majority of resolved records carry
a missing or garbled `growbot_river_learning_context.regime` (an upstream
serialization issue, not in a module this sprint touches).
`overfit_risk_model.normalize_label()` defensively buckets these as
`"unknown"` rather than polluting coverage counts, so regime coverage reads
near-zero for almost every parameter today -- that is the learning layer
behaving conservatively given real data quality, not a defect.

## Dashboard

The Tradingbot Control Center's existing **Learning Cockpit** page
(`dashboard/frontend/src/features/learning/`) was extended rather than
replaced:

- `GET /api/learning/intelligence` (`dashboard/backend/routers/learning_intelligence.py`)
  serves `bot.adaptive_learning_intelligence.build_adaptive_learning_intelligence()`:
  per-parameter evidence, the proposal maturity funnel, the overfit-risk
  monitor, wait-decision quality and missed-opportunity learning.
- `GET /api/parameters/proposal-funnel` (`dashboard/backend/routers/parameter_proposal_funnel.py`)
  serves the same evidence grouped by tier, with a `why_no_proposal` column
  per parameter.
- The existing `GET /api/status/run-summary` response gained an additive
  `learning_evidence_summary` / `decision_evidence_summary` /
  `run_evidence_summary` merge (`dashboard/backend/services/run_summary.py`,
  `dashboard/backend/services/learning_evidence_summary.py`) -- short,
  human-readable learning notes alongside the existing run summary, not a
  replacement of it.

All of this is read-only: the dashboard binds `127.0.0.1` only, has no code
path that writes `.env`, mutates state, calls Coinbase, or restarts anything
(see [`dashboard/README.md`](../dashboard/README.md) for the full security
notes), and none of the new endpoints change that.

## Regenerating the reports

```bash
PYTHONPATH=. python3 tools/build_adaptive_learning_intelligence.py
PYTHONPATH=. python3 tools/build_parameter_proposal_funnel.py
PYTHONPATH=. python3 tools/build_latest_learning_evidence_summary.py
PYTHONPATH=. python3 tools/build_adaptive_learning_depth_sprint_audit.py
```

These write to `reports/learning/*-latest.{json,md}` and
`reports/audits/adaptive-learning-depth-sprint-latest.{json,md}` (all
gitignored, consistent with every other report under `reports/` in this
repo). Every tool is read-only and safe to re-run at any time; none of them
touch `.env`, `state/approved_parameter_profile.json`, open orders/positions,
or Coinbase.

## Running the dashboard to view this

```bash
# backend
cd dashboard/backend
PYTHONPATH=/root/apps/Crypto/coinbase_bot python3 run.py

# frontend (separate shell)
cd dashboard/frontend
nvm use 22
npm run dev -- --host 127.0.0.1 --port 8080
```

See [`dashboard/README.md`](../dashboard/README.md) for the full setup,
including the SSH-tunnel access pattern for a remote host.

## What this sprint explicitly does not do

- No Coinbase API calls.
- No live order submission, cancellation or replacement.
- No automatic parameter apply -- `apply_ready_candidate` is unreachable by
  design; every proposal still requires the existing
  `autonomous_parameter_governor` ACK flow and `approved_parameter_profile`
  hash-ACK gate.
- No `.env` mutation.
- No `state/approved_parameter_profile.json` mutation.
- No trading-state mutation (`state/open_orders.json`, positions, etc.).
- No tradingbot service restart.
- No replacement of, or second source of truth alongside, GrowBot/River --
  see `growbot_river_cross_check` above.
