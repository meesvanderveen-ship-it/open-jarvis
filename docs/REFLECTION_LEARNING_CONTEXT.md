# Reflection Learning Context

## Doel

De reflection learning context is een read-only evaluatielaag voor beslissingen achteraf. De laag meet of WAIT, afgewezen setups, trades en probes achteraf lijken op:

- correct_wait
- missed_opportunity
- too_strict_wait
- correct_avoid
- false_signal_avoided
- good_trade
- bad_trade
- early_entry
- overtrading_risk
- insufficient_evidence

De laag plaatst geen orders, cancelt niets, vervangt niets, wijzigt geen `.env`, wijzigt geen approved profile en muteert geen productie order-state.

## Anti-hindsight regels

Een prijsstijging alleen is nooit voldoende voor `missed_opportunity`.

Een WAIT kan pas `missed_opportunity` of `too_strict_wait` worden als:

- setup of trigger zichtbaar was op decision_time
- entry plausibel fillable was
- MFE groter was dan fee plus spread plus slippage plus minimum edge
- MAE binnen acceptabele drawdown bleef
- invalidation niet eerst geraakt werd
- exit plausibel fillable was
- market intelligence geen risk warning had
- voor `too_strict_wait`: blocker wijst op een te strenge threshold of conservatieve gate

Als candle- of decision-data ontbreekt, gebruikt de evaluator `insufficient_evidence`.

## Cost-aware opportunity

De netto kans wordt berekend als:

```text
net_after_cost_opportunity_pct =
MFE_pct
- estimated_roundtrip_fee_pct
- estimated_spread_cost_pct
- estimated_slippage_buffer_pct
```

Defaults, zonder `.env` te muteren:

```text
REFLECTION_EVAL_DEFAULT_ROUNDTRIP_FEE_PCT=0.012
REFLECTION_EVAL_DEFAULT_SLIPPAGE_BUFFER_PCT=0.0025
REFLECTION_EVAL_MIN_NET_OPPORTUNITY_PCT=0.005
REFLECTION_EVAL_MAX_ACCEPTABLE_MAE_PCT=0.010
REFLECTION_EVAL_WINDOWS_HOURS=4,8,12,24
ENABLE_REFLECTION_LEARNING_CONTEXT=false
```

## Overtrading criteria

Trades, probes en approve_trade candidates worden gewaarschuwd als:

- MFE na kosten onvoldoende is
- MAE te hoog is
- invalidation of stop snel geraakt zou zijn
- spread of fee reward-to-cost te laag maakt
- het pad op een false breakout lijkt

Mogelijke labels zijn `bad_trade`, `early_entry`, `overtrading_risk`, `correct_avoid` en `false_signal_avoided`.

## State en rapporten

State:

```text
state/reflection_learning_context.json
```

Rapporten:

```text
reports/reflection/reflection-learning-latest.json
reports/reflection/reflection-learning-latest.md
reports/reflection/missed-opportunities-latest.json
reports/audits/reflection-learning-context-latest.json
reports/audits/reflection-learning-context-latest.md
```

Lokale bronnen:

```text
logs/analysis.jsonl
state/decision_outcomes.json
data/candles/*_1h.csv
research_data/coinbase/candles/.../study_window=3y.json
```

## Commands

```bash
python3 tools/build_reflection_learning_report.py --json --no-network
python3 tools/show_reflection_learning_status.py --json
python3 tools/summarize_missed_opportunities.py --json
python3 tools/write_reflection_learning_audit.py --json
```

Fixture-only smoke:

```bash
python3 tools/build_reflection_learning_report.py --fixture-only --no-network --json
```

## Feature-pack integratie

Optionele injectie is beschikbaar maar default uit:

```text
ENABLE_REFLECTION_LEARNING_CONTEXT=false
```

Bij expliciete enable wordt context geplaatst onder:

```json
{
  "decision_context": {
    "external_context": {
      "reflection_learning": {
        "available": true,
        "stale": false,
        "summary": {},
        "can_authorize_execution": false,
        "can_block_execution": false,
        "can_mutate_parameters": false
      }
    }
  }
}
```

Deze context mag de judge informeren en audits verrijken. Deze context mag geen trade goedkeuren, geen BUY/SELL forceren, geen gates overslaan en geen parameters wijzigen.

## Candidate proposals

Bij voldoende bewijs mag het rapport een candidate aanbevelen met:

```json
{
  "safe_to_activate_now": false,
  "requires_operator_review": true
}
```

Dit is alleen rapportage. Activatie vereist een apart operator review/ACK-pad en blijft los van learning-to-execution.

## Adaptive Policy Lab

De Reflection Learning Context blijft de bron voor achteraf labels. Adaptive Policy Lab bouwt hier bovenop en leest `reports/reflection/reflection-learning-latest.json` om validated conclusions te aggregeren per setup, blocker, ticker en marktregime. Die laag mag pas bij harde samplegrenzen report-only parameter-candidates onder `reports/adaptive_policy/` schrijven.

Adaptive Policy Lab geeft geen execution authority aan reflection learning. Beide blijven context-only/report-only met `can_authorize_execution=false`, `can_block_execution=false` en `can_mutate_parameters=false`.

Adaptive Policy Lab gebruikt daarnaast extra anti-overfitting gates voordat een candidate mag ontstaan: minimale effectgrootte, confidence interval buiten huidige waarde, richtingstabiliteit over meerdere report-runs, shrinkage richting kandidaatwaarde en market-regime enrichment coverage. Deze checks gebruiken reflection-output als input, maar kunnen geen orders autoriseren en kunnen geen live parameters muteren.

## Regime Persistence

Reflection Persistence bewaart voortaan raw en enriched regimevelden naast elkaar in de reflection ledger en parameter pressure ledger. `market_regime` blijft de raw reflectionwaarde, terwijl `adaptive_market_regime` de verrijkte analysewaarde bevat.

Voorbeeld:

```json
{
  "raw_market_regime": "unknown",
  "adaptive_market_regime": "network_supportive_liquidity_neutral",
  "regime_source": "market_intelligence",
  "regime_enriched": true
}
```

Dit maakt candidate analysis uitlegbaar zonder activation te versoepelen. Als er maar een enriched regime beschikbaar is, blijft de market-regime gate geblokkeerd totdat de vereiste regime-diversiteit aanwezig is.
