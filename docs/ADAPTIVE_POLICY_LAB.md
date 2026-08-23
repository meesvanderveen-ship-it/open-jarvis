# Adaptive Policy Lab

## Doel

Adaptive Policy Lab is een GrowBot-inspired, report-only optimalisatielaag bovenop de bestaande Reflection Learning Context. Reflection Learning blijft verantwoordelijk voor achteraf labelen van beslissingen. Adaptive Policy Lab gebruikt die labels pas daarna voor aggregatie, overfitting-checks en eventuele candidate profiles.

De laag handelt niet direct. Er is geen execution authority, geen risk-gate bypass en geen automatische parameter-mutatie.

## Leerflow

```text
botbeslissing loggen
→ reflection_learning_context evalueert WAIT/trade/probe achteraf
→ labels zoals missed_opportunity, too_strict_wait, correct_wait, overtrading_risk
→ Adaptive Policy Lab filtert validated conclusions
→ aggregatie per setup/blocker/ticker/regime
→ harde sample gates en robuuste statistiek
→ candidate profile onder reports/adaptive_policy/
→ stable hash
→ operator review + ACK
→ eventuele activatie later via bestaande approved-profile/hash route
```

## Geldige conclusie

Een reflection-uitkomst telt alleen mee als validated conclusion wanneer:

- label niet `insufficient_evidence` is
- `decision_time` en `ticker` bekend zijn
- `setup_type` of `main_blocker` bekend is
- future window volledig is geëvalueerd
- MFE en MAE berekend zijn
- fee, spread en slippage zijn meegenomen
- net-after-cost opportunity is berekend
- anti-hindsight reason aanwezig is

Niet meetellen: missing candle data, missing decision context, corrupt logs en insufficient evidence.

## Harde samplegrenzen

Defaults:

```text
ADAPTIVE_MIN_TOTAL_VALIDATED_CONCLUSIONS = 300
ADAPTIVE_MIN_RELEVANT_CONCLUSIONS_PER_PARAMETER = 150
ADAPTIVE_MIN_DIRECTIONAL_ERROR_LABELS = 40
ADAPTIVE_MIN_SEPARATE_DAYS = 7
ADAPTIVE_MIN_MARKET_REGIMES = 2
ADAPTIVE_MIN_TICKERS_PER_GENERAL_CHANGE = 3
ADAPTIVE_MIN_OUT_OF_SAMPLE_CONCLUSIONS = 75
ADAPTIVE_MAX_SINGLE_STEP_PARAM_CHANGE_PCT = 10
ADAPTIVE_DEFAULT_SINGLE_STEP_PARAM_CHANGE_PCT = 5
ADAPTIVE_MIN_EFFECT_SIZE_PCT = 5
ADAPTIVE_CONFIDENCE_BUFFER_PCT = 3
ADAPTIVE_REQUIRE_DIRECTION_STABILITY_RUNS = 3
ADAPTIVE_REQUIRE_CONFIDENCE_INTERVAL_EXCLUDES_CURRENT = true
ADAPTIVE_SHRINKAGE_FACTOR = 0.50
ADAPTIVE_MIN_REGIME_ENRICHMENT_COVERAGE_PCT = 80
```

Bij onvoldoende bewijs wordt geen parameterwijziging voorgesteld.

## Anti-overfitting

Adaptive Policy Lab vereist meerdere dagen, meerdere regimes, out-of-sample conclusions en genoeg directionele foutlabels. Globale wijzigingen vereisen multi-ticker en multi-setup bewijs. Setup-specifiek bewijs blijft setup-specifiek.

Correct waits, false-signal avoids en overtrading-risk labels tellen tegen versoepeling mee. Negatieve net-after-cost kansen blokkeren versoepeling.

Extra hardening:

- effect-size/deadband: robuuste target moet minimaal 5% van huidige waarde afwijken
- confidence gate: het confidence interval moet de huidige waarde uitsluiten
- direction stability: dezelfde parameter/scope/richting moet minimaal 3 opeenvolgende report-runs zichtbaar zijn
- regime enrichment: minimaal 80% van validated conclusions moet een niet-unknown regime hebben
- shrinkage: na de normale 5%/10% caps beweegt de candidate maar 50% van die stap

History wordt alleen als rapportage bijgehouden in:

```text
reports/adaptive_policy/history/adaptive-policy-candidate-history.jsonl
```

Dit is geen production state en wordt niet gebruikt om orders te autoriseren.

## Robuuste aggregatie

Per candidate berekent de lablaag:

- raw mean
- median
- 10% trimmed mean
- winsorized mean
- confidence interval
- outlier count
- sample count
- separate days
- regimes
- tickers
- net-after-cost effect
- overtrading effect
- correct-wait counterweight
- false-signal counterweight

De candidate value gebruikt een conservatieve stap richting trimmed mean/median, met standaard 5% cap en absolute 10% cap.

Daarna wordt shrinkage toegepast:

```text
candidate_uncapped = conservative_step_toward(current, robust_target)
candidate_value = current + (candidate_uncapped - current) * ADAPTIVE_SHRINKAGE_FACTOR
```

Met default `ADAPTIVE_SHRINKAGE_FACTOR=0.50` beweegt de candidate dus half zo ver als de reeds gecapte stap.

## Market-regime enrichment

Regime wordt verrijkt in deze volgorde:

1. reflection evaluation zelf, als `market_regime` of vergelijkbaar veld aanwezig is
2. `state/market_intelligence_context.json`, alleen als context
3. candle/trend context indien aanwezig
4. anders `unknown`

Voorbeelden van samengestelde labels:

```text
network_supportive_liquidity_neutral
network_unknown_liquidity_neutral
trend_bullish_volatility_normal
trend_bearish_volatility_high
unknown
```

Market intelligence blijft context-only:

```text
can_authorize_execution=false
can_block_execution=false
can_mutate_parameters=false
```

## Label Pressure

Labels worden vertaald naar parameterdruk:

```text
too_strict_wait        -> loosen +1.00
missed_opportunity    -> loosen +0.75
good_trade            -> loosen +0.10
correct_wait          -> tighten +0.10
correct_avoid         -> tighten +0.50
false_signal_avoided  -> tighten +0.75
bad_trade             -> tighten +1.00
early_entry           -> tighten +0.85
overtrading_risk      -> tighten +1.00
```

De score wordt gewogen met confidence, setup visibility, fillability, net-after-cost opportunity, drawdown safety en regimekwaliteit. Alleen wanneer de netto pressure de richting ondersteunt én alle sample-, effect-, confidence-, stability- en regime-gates slagen, mag een report-only candidate ontstaan.

## Cost-aware reward

Een candidate moet positief zijn na kosten:

```text
reward =
net_after_cost_opportunity_score
+ captured_MFE_score
- MAE_penalty
- fee_drag_penalty
- overtrading_penalty
- missed_opportunity_penalty
- risk_violation_penalty
- instability_penalty
```

Negatieve net-after-cost opportunity blokkeert loosening.

## Toegestane parameters

Report-only candidates mogen alleen gaan over:

- `PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT`
- `PHASE_D2_MIN_REWARD_TO_FEE_RATIO`
- `PHASE_D2_MIN_REWARD_TO_RISK_RATIO`
- `MAX_SPREAD_PCT`
- `EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT`
- `setup_type_specific_trigger_strictness`
- `starter_probe_eligibility_thresholds` als bestaande starter/probe-code aanwezig is

Verboden: credentials, execution mode, replication, neural execution, learning-to-execution flags, Mode B/C ACKs, D2/D3 enablement, lifecycle apply flags, no-naked-sell guards en oversell guards.

## Paths

Inputs:

```text
reports/reflection/reflection-learning-latest.json
state/reflection_learning_context.json
```

Outputs:

```text
reports/adaptive_policy/adaptive-policy-lab-latest.json
reports/adaptive_policy/adaptive-policy-candidate-latest.json
reports/adaptive_policy/adaptive-policy-candidate-latest.md
reports/adaptive_policy/history/adaptive-policy-candidate-history.jsonl
reports/audits/adaptive-policy-lab-latest.json
reports/audits/adaptive-policy-lab-latest.md
```

## Commands

```bash
python3 tools/build_adaptive_policy_candidate.py --json
python3 tools/show_adaptive_policy_lab_status.py --json
python3 tools/write_adaptive_policy_audit.py --json
```

## Feature-pack context

Default disabled:

```text
ENABLE_ADAPTIVE_POLICY_CONTEXT=false
```

If explicitly enabled, the helper can add context under `decision_context.external_context.adaptive_policy_context`, always with:

```text
can_authorize_execution=false
can_block_execution=false
can_mutate_parameters=false
```

## Activatie

Adaptive Policy Lab schrijft alleen candidates onder `reports/`. Activatie mag later alleen via bestaande approved-profile/hash-gating route:

```text
review candidate
verify hash
write approved profile via existing approved-profile process
set exact ACK/hash
operator-only service restart if separately approved
```

## Autonomous Parameter Governor

Adaptive Policy Lab generates report-only candidates. Autonomous Parameter Governor may later validate and activate a bounded candidate only when explicitly enabled, ACKed, all adaptive gates pass, no open orders/positions exist, cooldown/rate limits pass, and backup/rollback plans are written. Adaptive Policy Lab itself remains report-only and cannot mutate live parameters.

## Raw And Enriched Regimes

Reflection rows now keep raw and adaptive regime fields separately:

- `raw_market_regime`: the original reflection/candle regime, often `unknown`
- `adaptive_market_regime`: enriched regime used for adaptive evidence grouping
- `regime_source`: `reflection`, `market_intelligence`, `candle_context`, or `unknown`
- `regime_enriched`: true when enrichment produced a usable adaptive regime

Priority is explicit adaptive regime, non-unknown raw market regime, market intelligence network/liquidity regime, candle trend/volatility regime, then `unknown`.

Candidate analysis should be read from the enriched regime fields. If raw is `unknown` but market intelligence says supportive/neutral, the adaptive regime is `network_supportive_liquidity_neutral`; this counts as one unique adaptive regime and does not satisfy the two-regime activation gate by itself.

Parameter Candidate Analysis reports two coverage numbers:

- `ledger_regime_coverage_pct`: coverage in the reflection/pressure ledger rows used by the analysis.
- `adaptive_gate_regime_coverage_pct`: coverage from the Adaptive Policy Lab regime enrichment gate.

These can differ because the ledger view explains source evidence while the adaptive gate evaluates the enriched candidate input. If a known enriched regime exists, `unknown` is not shown as an adaptive/enriched regime.

Effect-size and confidence interval diagnostics may be calculated even when a higher gate, such as `insufficient_market_regimes`, blocks activation. In that case the report shows `used_for_activation=false` and `not_used_reason=candidate_blocked_by_...`; the values are explanatory only.

Weighted pressure is score-based, not event-count based. A smaller number of high-quality missed/too-strict events can outweigh many low-weight counterweight events after confidence, net-after-cost, drawdown-safety, regime and label-weight adjustments.

Direction stability grows through repeated report-only sidecar/candidate runs written to `reports/adaptive_policy/history/adaptive-policy-candidate-history.jsonl`. Three consecutive matching parameter/scope/direction entries are required before the stability gate can pass.
