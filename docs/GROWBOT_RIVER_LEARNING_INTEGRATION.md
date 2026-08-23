# GrowBot/River learning integration

The GrowBot/River layer is a report-only parameter-learning sidecar. It does
not create trades, submit/cancel/replace orders, instantiate a new trader, or
change `.env`, `BotConfig`, open orders, positions, or an approved profile.

Its place in the existing workflow is:

```text
feature_pack → LLM/judge → deterministic risk → D2 plan → C4.3 entry → D3 exit
    → outcome/reflection → existing learning/adaptive profile
    → GrowBot/River sidecar → parameter proposals → adaptive_policy_lab
    → parameter_candidate_analysis → autonomous_parameter_governor
    → approved_parameter_profile (exact hash ACK) → BotConfig
```

The order above is intentional. GrowBot/River adds evidence and bounded
parameter candidates; it cannot bypass C4.3/D3, deterministic risk, the
adaptive-policy gates, the governor's open-order/open-position checks, or the
approved-profile hash acknowledgement.

## Upstream provenance and data model

The adapter verifies the concrete upstream project rather than claiming that a
conceptual episode format is GrowBot source code. At commit
`0eccd6460c289fbae710a9efc2fee57bfafa65c5`,
[`britcruise9/GrowBot`](https://github.com/britcruise9/GrowBot) contains
Raspberry Pi hardware setup modules and a MuJoCo body asset. Its README states
that the training harness, reward functions, policies and agent runtime are
still in development. It is licensed CC BY-NC 4.0. Consequently, this bot does
not vendor, import or execute that source: there is no published GrowBot
learning API to invoke, and its licence requires an operator legal review for a
trading use case.

`bot/growbot_learning_adapter.py` records this exact provenance in every
report. It can inspect a user-supplied local source tree via
`--growbot-source PATH`, but remains manifest-only until an operator provides
a documented learning API with a trading-compatible licence. Third-party
GrowBot code has no execution authority and is never dynamically imported.

The episode contract is an isolated trading adapter:

The adapter converts existing logs into a GrowBot-style episode:

```text
episode = trade cycle or missed opportunity
state = feature_pack + regime + decision context
action = parameter setting / threshold / sizing choice
reward = net PnL, avoided loss, missed opportunity, fill quality, fee impact
memory = append-only reports/growbot_river/history/episodes.jsonl
policy = report-only parameter proposal
```

Every cycle validates this contract separately from model quality. It reports
immutable feature-state coverage, observed regime coverage, non-zero outcome
coverage and parameter-direction evidence. Missing fields remain blockers;
they are never backfilled from the current market. A candidate cannot use this
contract to bypass the existing adaptive/governor evidence gates.

New decision outcomes, paper execution outcomes, trade reflections and
reflection-learning hindsight evaluations carry `growbot_river_learning_context`
(schema v2), an immutable source-time snapshot. It contains only an allowlist
of numeric decision/market features (confidence, net edge, reward-to-fee,
reward-to-risk, spread, volatility, trend strength, drawdown, fee, slippage,
MFE/MAE, liquidity, volume and orderbook imbalance), a compact categorical
`context` (ticker, setup type, fill status, exit result) and observed regime
dimensions. Raw feature packs, prompts, model responses, credentials and
account data are explicitly excluded. Reflection evaluation and persistence
preserve a pre-existing snapshot untouched; only when a decision carries no
state or regime yet does the evaluator derive one from evidence it already
computes (confidence, cost-aware net edge, spread/fee/slippage, MFE/MAE and a
strictly-before-decision-time candle lookback). The GrowBot adapter unwraps
trade-reflection log events before creating a closed-trade episode, and drops
periodic count-only heartbeat events (`*_by_engine`,
`trade_learning_cycle_summary`) instead of counting them as zero-evidence
episodes. Existing history is not rewritten or enriched retroactively.

### Compact regime taxonomy

When no explicit/historical regime tag is available anywhere in the evidence,
`bot/growbot_river_learning_contract.classify_compact_regime_from_metrics`
buckets whatever numeric trend/volatility/drawdown evidence exists into one of
seven canonical regimes: `trend_up`, `trend_down`, `range_chop`,
`high_volatility`, `low_volatility`, `drawdown_risk_off`, `unknown`. This is a
last-resort classifier only — it never overrides an explicit or historical
regime string (for example an existing `adaptive_market_regime` key), and it
grants no execution or parameter-mutation authority. Trend/volatility/drawdown
metrics are derived only from candles that are strictly at-or-before the
moment being described (`derive_regime_metrics_from_candles`), so the
classification carries no hindsight leakage.

It consumes the existing reflection report, decision outcomes, execution
outcomes, trade reflections and historical backtest summary. The existing neural
shadow-policy report is retained as provenance-only context; it is not a direct
parameter vote. Inputs remain read-only. The memory ledger is append-only and
deduplicated by a stable episode id.

River uses its actual streaming API (`learn_one` / `predict_one`) when it is
available: a persistent logistic classifier estimates good/bad outcomes, a
linear regressor estimates reward per candidate parameter, and ADWIN reports
reward drift. Their model snapshot is stored only below
`reports/growbot_river`; it is integrity-manifested, report-only and never read
by the trading runtime. Without River, the deterministic incremental-statistics
fallback remains active.

Fallback and native River keep separate processed-episode markers. Therefore,
installing/using River later gives the native model one source-bounded bootstrap
batch; it does not mistake fallback statistics for native training. A legacy
native snapshot without that marker is rebuilt only inside
`reports/growbot_river`, then processed IDs prevent further replay. This has no
BotConfig, profile, execution or exchange effect.

River 0.23 declares `pandas<3`, while the core bot currently pins
`pandas==3.0.1`. To avoid changing the existing runtime, River is defined in
[`requirements-river-sidecar.txt`](../requirements-river-sidecar.txt) for an
isolated report-only environment; it is deliberately not a core dependency.
Neither backend is an execution model.

## Learnable parameter registry

`bot/learnable_parameter_registry.py` has 47 bounded candidates across:

- entry quality: net edge, reward/fee, reward/risk, confidence and setup thresholds;
- C4.3/orderbook: spread, offsets, TTL, replace limits, liquidity and imbalance;
- sizing: default/min/max quote, confidence/edge/regime/volatility/drawdown multipliers;
- D2/D3 exits: target distance, TP1/TP2/runner allocation, stop, trailing and timeout;
- market filters: ticker score, volume, volatility, trend, market-intelligence/reflection/neural weights;
- workflow: order limits, cooldown, ticker rotation, missed-opportunity sensitivity and overtrading penalty.

Every item has bounds, step ranges, direction semantics, dependencies, rollback
requirements, evidence requirements, safety class and current activation route.
The registry distinguishes:

- `current_governor_and_approved_profile`: currently allowlisted by both routes;
- `approved_profile_only_manual_governance`: existing profile support but not the autonomous governor;
- `adaptive_review_only_not_currently_profile_routable` and
  `research_only_profile_extension_required`: useful for evidence and manual
  design, never activation candidates today.

No registry entry is automatically activatable.

## Tuning phases

`bot/parameter_step_scheduler.py` limits candidates by phase:

| Phase | Step | Maximum | Entry condition |
| --- | --- | --- | --- |
| `coarse_tuning` | 5–15% | 5 parameters | default start state |
| `stabilization` | 2–5% | 3 parameters | at least 120 episodes, 2 regimes, and 3 consistent earlier proposal runs |
| `fine_tuning` | 0.25–2% | 1 parameter | at least 500 episodes, 3 regimes, and 5 consistent earlier proposal runs |

Coarse suggestions are visible in the report but cannot bridge to an adaptive
candidate. The bridge accepts only current allowlisted parameters from
stabilization/fine tuning, with confidence >= 0.75, enough evidence, existing
adaptive-lab reflection thresholds and the normal direction-stability/effect
gates. It remains operator-review-only.

`backtest` is an evidence source, not a market regime. Only observed market
regimes from the source records count toward stabilization/fine tuning. A
report with unknown regime coverage therefore remains in `coarse_tuning`; the
sidecar must not invent historical regimes from current market context. Proposal
history also advances only when the append-only memory receives new episodes,
not when a report is recalculated or an online-model contract is migrated.

Example proposal:

```json
{
  "parameter": "MAX_SPREAD_PCT",
  "direction": "loosen",
  "confidence": 0.71,
  "suggested_step_pct": 3.0,
  "phase": "stabilization",
  "reason": "missed opportunities clustered around spread_too_high"
}
```

## Real blockers vs. historical readiness labels

`build_growbot_river_readiness()` distinguishes blockers that actually gate
`stabilization_ready` (`STABILIZATION_GATING_BLOCKERS` in
`bot/growbot_river_readiness.py`) from labels that merely describe a
permanent, non-blocking upstream status. The one example today is
`growbot_upstream_learning_runtime_unavailable`: it reflects GrowBot
upstream's CC-BY-NC-4.0 license and lack of a published training/policy
runtime, and it never gated any readiness tier even before this distinction
was made explicit. Once `river_available=true` (the native River sidecar, or
its deterministic report-only fallback, already supplies the live learning
runtime), this label is removed from the active `blockers` list and reported
instead under `historical_readiness_labels` with
`status: historical_stale_label_not_an_active_blocker` -- it self-resolved in
practice the moment River became available and is not waiting on anything
further. If River is unavailable, the label still appears as a real blocker.

The remaining, currently-active entries in `STABILIZATION_GATING_BLOCKERS`
are surfaced in `stabilization_readiness.real_blockers`, each tagged with a
`category` and `self_resolves_with_more_live_episodes`. As of this writing,
on the live report, the only two active entries are
`feature_snapshot_coverage_below_80pct` and
`market_regime_coverage_below_80pct` -- both `awaiting_live_episode_volume`.
`real_blockers_summary` states this in plain language without hard-coding a
blocker count, e.g.:

> The only currently-active real blocker(s) are: feature_snapshot_coverage_below_80pct, market_regime_coverage_below_80pct. Each is categorized as awaiting_live_episode_volume and self-resolves with more live episodes -- no further code change, River install, or operator action is required.

This requires no further code change: `stabilization_ready` flips to `true`
automatically on the next `tools/run_growbot_river_learning_cycle.py` run once
enough new live episodes cross both 80% thresholds -- see
`estimate_forward_episode_requirements()` for a concrete episode-count
estimate.

## Fast-start autotune tier

The strict `stabilization_ready` gate (>=80% feature-state coverage, >=80%
known-regime coverage, >=2 distinct regimes, River native sidecar available,
walk-forward passed) is intentionally conservative, but it can take hundreds
of additional live decision cycles to clear purely on coverage volume, even
when a specific candidate's own evidence is already strong. `fast_start_autotune_ready`
is a second, deliberately lower-volume readiness tier for small, reversible,
`fine_tuning`-sized steps only. It does not replace, lower or bypass the
strict tier, and it grants no execution or apply authority of its own: the
unchanged `autonomous_parameter_governor` ACK/candidate-hash/cooldown/
open-order/open-position/regime-enrichment/effect-size gates remain the only
real authorization path for any actual `approved_parameter_profile` change.

There are two independent halves to this tier, both computed report-only in
`bot/growbot_river_readiness.py` and `bot/growbot_river_governor_bridge.py`:

**Sidecar evidence base** (`build_fast_start_autotune_readiness`, not
parameter-specific):

| Requirement | Threshold |
| --- | --- |
| Feature-state coverage | >= 50% (vs 80% for `stabilization_ready`) |
| Known-regime coverage | >= 45% (vs 80%) |
| Distinct observed regimes | >= 3 |
| River native sidecar | available |
| River walk-forward validation | passed |

**Per-candidate eligibility** (`evaluate_fast_start_candidate_eligibility`,
specific to the top-ranked GrowBot/River proposal):

| Requirement | Threshold |
| --- | --- |
| Confidence | >= 0.85 |
| Evidence count | >= 75 |
| Distinct regimes for this candidate | >= 3 |
| Direction-stable prior proposal runs | >= 3 |
| Suggested step size | within the parameter's `fast_start_max_step_pct` (the normal `fine_tuning` ceiling of 2%, or half that for extra-caution parameters) |
| Candidate value | within the registry's `min`/`max` rails |
| Parameter | on the fast_start low-risk allowlist (below) and already `current_governor_and_approved_profile`-routable |
| Apply scope | max 1 parameter per apply, rollback snapshot mandatory, `BotConfig` validation mandatory |

`fast_start_autotune_ready` in the bridge status is the AND of both halves.
It is reported alongside, never instead of, `strict_stabilization_ready` and
the real `auto_apply_eligible` (the unchanged governor's own `apply_ready`
signal). A candidate can be `fast_start_autotune_ready=true` while
`auto_apply_eligible` stays `false` -- that only means the evidence is strong
enough to be worth an operator/governor look; the governor still decides.

### Fast-start low-risk allowlist

Deliberately narrower than the full governor `ALLOWED_PARAMETERS`/
`APPROVED_PARAMETER_PROFILE_WHITELIST`:

- `PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT`
- `PHASE_D2_MIN_REWARD_TO_FEE_RATIO`
- `PHASE_D2_MIN_REWARD_TO_RISK_RATIO`
- `MAX_SPREAD_PCT` -- allowlisted, but capped at half the normal `fine_tuning`
  step ceiling (1% instead of 2%) because a spread change affects fill/no-fill
  behaviour directly rather than only a downstream profitability threshold.

`JUDGE_MIN_GATE_CONFIDENCE` is explicitly **not** fast-start-eligible today:
it is not in the governor's `ALLOWED_PARAMETERS` or
`APPROVED_PARAMETER_PROFILE_WHITELIST`, and its registry `safety_class` is
`high_risk_manual_only`. It would need a deliberate, separate extension of
the approved-profile route before it could ever join this tier.

### Worked example: the live top candidate as of 2026-06-22

The actual top-ranked GrowBot/River proposal observed live was
`PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT`, `direction=loosen`,
`confidence=0.8998`, `evidence_count=207`, 5 distinct regimes,
`direction_stable_runs=12`, `suggested_step_pct=1.8247`. Checked against the
per-candidate table above, every single criterion already passes: confidence,
evidence count, regime diversity, direction stability, step size, value
rails, and allowlist membership. The only thing keeping
`fast_start_autotune_ready` at `false` for this candidate is the sidecar
evidence base's feature-state coverage, which was `46.1%` against the `50%`
floor (known-regime coverage, `45.75%`, already clears its `45%` floor). In
other words: this specific candidate is one coverage point away from
fast-start eligibility, not weeks away from the strict 80%/80% bar -- exactly
the gap this tier exists to make visible.

## Operator commands

Run the sidecar and refresh only its report chain:

```bash
python3 tools/run_growbot_river_learning_cycle.py --json
python3 tools/show_growbot_river_learning_status.py --json
python3 tools/build_growbot_river_readiness.py --json
```

To inspect a local GrowBot checkout without importing it:

```bash
python3 tools/run_growbot_river_learning_cycle.py --growbot-source /path/to/GrowBot --json
```

To test the actual River integration without replacing the core bot runtime,
create an isolated environment and run the sidecar with that interpreter:

```bash
python3 -m venv /opt/coinbase-river-sidecar
/opt/coinbase-river-sidecar/bin/pip install -r requirements-river-sidecar.txt
PYTHONPATH=/root/apps/Crypto/coinbase_bot /opt/coinbase-river-sidecar/bin/python tools/run_growbot_river_learning_cycle.py --json
```

The first command writes only reports and append-only learning memory. It does
not invoke the governor. The existing operator flow remains available for any
later profile change:

```bash
python3 tools/analyze_parameter_candidate.py --json
python3 tools/show_autonomous_parameter_governor_status.py --json
```

Do not activate a profile from a GrowBot/River report directly. Activation
remains the existing action requiring the exact approved-profile hash ACK,
normal governor gates and all live safety checks.

### GrowBot/River → governor bridge

`bot/growbot_river_governor_bridge.py` is a read-only status aggregator, not a
second activation route. It reads the already-computed sidecar/candidate/
readiness reports plus the existing governor's own `validate_governor`, and
answers one question: is a GrowBot/River-sourced proposal currently eligible
to flow through the unchanged
`growbot_river_learning → adaptive_policy_lab(_growbot_river_supplemental_changes)
→ parameter_candidate_analysis → autonomous_parameter_governor →
approved_parameter_profile → BotConfig` route without a new gate?

```bash
python3 tools/show_growbot_river_governor_bridge_status.py --json
```

This status now also reports `strict_stabilization_ready`,
`fast_start_autotune_ready`, `fast_start_candidate_eligibility` (with its own
`blocking_reasons`), `first_autonomous_candidate_if_fast_start`,
`expected_parameter_change` and a `cooldown` block -- see
[Fast-start autotune tier](#fast-start-autotune-tier) above. These are purely
additional report fields: `auto_apply_eligible` is unchanged and still
reflects only the real governor's own `apply_ready` signal, never the
fast_start tier.

`tools/prepare_growbot_river_governor_candidate.py` chains the sidecar
refresh, the live-cycle readiness refresh and the bridge status into one call,
and only with `--apply` additionally invokes the existing
`bot.autonomous_parameter_governor.run_governor` -- exactly as
`tools/run_autonomous_parameter_governor.py --apply` would, still gated by the
unchanged ACK/mode/cooldown/regime/evidence/open-order safety rails:

```bash
python3 tools/prepare_growbot_river_governor_candidate.py --json          # refresh + status only
python3 tools/prepare_growbot_river_governor_candidate.py --apply --json  # also runs the existing governor apply path
```

Once an operator has set `AUTONOMOUS_PARAMETER_GOVERNOR_ACK` once in the
environment (the governor's existing one-time ACK, not a per-change
approval), and `stabilization_readiness.ready` plus the governor's own gates
pass, this command is the unattended path by which a GrowBot/River proposal
reaches `approved_parameter_profile` without an operator decision on each
individual parameter change. It still cannot loosen, skip or duplicate any
existing gate -- it can only run them.

## Outputs

- `reports/growbot_river/growbot-river-learning-latest.json`: master report,
  registry, phase decision, candidate/blocked proposals and downstream report
  references.
- `reports/growbot_river/growbot-episode-report-latest.json`: input coverage,
  reward analysis and episode-memory result.
- `reports/growbot_river/river-online-learning-latest.json`: incremental
  classifier/statistics, expected reward, rankings and regime drift.
- `reports/growbot_river/river-native-models.pkl` and manifest: integrity
  checked River snapshot when the optional River package is available.
- `reports/growbot_river/history/episodes.jsonl`: append-only memory.
- `reports/growbot_river/history/proposal-history.jsonl`: append-only history
  used only for phase/direction stability.
- `reports/growbot_river/growbot-river-readiness-latest.json`: consolidated
  report-only contract, River, regime, adaptive and activation readiness gate,
  now including a `fast_start_autotune_readiness` block alongside the
  existing `stabilization_readiness`, plus `readiness.fast_start_autotune_ready`
  and `readiness.fine_tuning_ready` (now computed from the live tuning phase
  instead of being permanently `false`).
- `reports/growbot_river/growbot-river-governor-bridge-status-latest.json`:
  the bridge status described above, including `strict_stabilization_ready`,
  `fast_start_autotune_ready`, `fast_start_candidate_eligibility`,
  `first_autonomous_candidate_if_fast_start`, `expected_parameter_change` and
  `cooldown`.

All outputs explicitly set `parameter_mutation_allowed: false` and
`execution_authority: false`.

## Depth layer built on top of this

[`docs/ADAPTIVE_LEARNING.md`](ADAPTIVE_LEARNING.md) describes a report-only
enrichment layer (`bot/adaptive_learning_intelligence.py`,
`bot/overfit_risk_model.py`, `bot/parameter_proposal_scoring.py`,
`bot/regime_parameter_profiles.py`) that reads the
`growbot-river-learning-latest.json` output above plus the existing decision/
execution outcome logs, and adds proposal-maturity tiers, overfit-risk
scoring and regime-segmented narratives on the dashboard. It is not a second
learning system: it cross-checks every parameter it can map against this
report's own `river.parameter_signals`/`proposals`/`blocked_proposals`, and
the existing governor/approved-profile route above remains the only apply
path.
