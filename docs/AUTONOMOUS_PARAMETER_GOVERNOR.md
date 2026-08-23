# Autonomous Parameter Governor

## Doel

Autonomous Parameter Governor is een bounded activation-laag bovenop Reflection Learning Context en Adaptive Policy Lab. De governor leert niets zelf, verzint geen parameters en kan geen orders autoriseren. Hij valideert alleen een bestaande Adaptive Policy candidate en kan later, met expliciete ACK en alle safety gates groen, een allowlisted parameterwijziging via de approved-profile route voorbereiden of toepassen.

Flow:

```text
Reflection Learning Context
-> Adaptive Policy Lab
-> candidate profile
-> Autonomous Parameter Governor
-> bounded activation
-> monitoring
-> rollback
```

## Geen Order Authority

De governor heeft altijd:

```text
can_authorize_orders=false
source_policy=autonomous_parameter_governor_bounded_no_execution_authority
```

Hij mag geen BUY/SELL doen, geen cancel/replace/apply uitvoeren, geen risk gates overslaan en geen service lifecycle uitvoeren.

## Candidate Versus Activation

Adaptive Policy Lab schrijft report-only candidates onder:

```text
reports/adaptive_policy/adaptive-policy-candidate-latest.json
```

Een Adaptive candidate houdt `safe_to_activate_now=false`, omdat die laag zichzelf niet activeert. De governor voert daarna een aparte validatie uit en produceert:

```json
{
  "governor_activation_allowed": false,
  "governor_reason": "candidate_not_available"
}
```

Alleen de governor mag later, met expliciete enable + ACK + safe state, een bounded approved-profile activation uitvoeren.

## Env Flags

Documented defaults:

```text
ENABLE_AUTONOMOUS_PARAMETER_GOVERNOR=false
AUTONOMOUS_PARAMETER_GOVERNOR_MODE=report_only
AUTONOMOUS_PARAMETER_GOVERNOR_ACK=
AUTONOMOUS_PARAMETER_GOVERNOR_REQUIRED_ACK=I_APPROVE_AUTONOMOUS_PARAMETER_GOVERNOR_BOUNDED_PROFILE_ACTIVATION
AUTONOMOUS_PARAMETER_GOVERNOR_ROLLBACK_ACK=
AUTONOMOUS_PARAMETER_GOVERNOR_REQUIRED_ROLLBACK_ACK=I_APPROVE_AUTONOMOUS_PARAMETER_GOVERNOR_ROLLBACK
AUTONOMOUS_PARAMETER_MAX_CHANGES_PER_24H=1
AUTONOMOUS_PARAMETER_COOLDOWN_HOURS=24
AUTONOMOUS_PARAMETER_APPLY_ONLY_WHEN_NO_OPEN_ORDERS=true
AUTONOMOUS_PARAMETER_APPLY_ONLY_WHEN_NO_OPEN_POSITIONS=true
AUTONOMOUS_PARAMETER_REQUIRE_FULL_POC_READY=true
AUTONOMOUS_PARAMETER_REQUIRE_MODE_C_READY=true
AUTONOMOUS_PARAMETER_REQUIRE_CANDIDATE_HASH_STABLE=true
AUTONOMOUS_PARAMETER_REQUIRE_CANDIDATE_NOT_STALE=true
AUTONOMOUS_PARAMETER_MAX_TOTAL_CHANGE_PCT=10
AUTONOMOUS_PARAMETER_MAX_PARAMETERS_PER_ACTIVATION=1
AUTONOMOUS_PARAMETER_WRITE_PENDING_ONLY=true
AUTONOMOUS_PARAMETER_ROLLBACK_ON_HEALTH_WARNING=true
```

Codex does not mutate `.env`.

## Modes

`report_only`: never applies. Status and dry-run reports only.

`prepare_only`: writes pending activation plan only.

`apply_when_safe`: can apply only when all candidate gates, ACK, readiness, open-order/open-position, cooldown, backup and rollback checks pass.

## Required Candidate Gates

The governor never bypasses Adaptive Policy Lab. Activation requires:

- `candidate_available=true`
- stable candidate hash
- candidate not stale
- sample thresholds passed
- at least 2 market regimes
- regime enrichment passed
- effect-size/deadband passed
- confidence gate passed
- direction stability passed
- shrinkage applied
- robust averaging present
- proposed changes present
- max one parameter per activation by default

## Allowlist

Allowed:

- `PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT`
- `PHASE_D2_MIN_REWARD_TO_FEE_RATIO`
- `PHASE_D2_MIN_REWARD_TO_RISK_RATIO`
- `MAX_SPREAD_PCT`
- `EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT`
- `setup_type_specific_trigger_strictness`
- `starter_probe_eligibility_thresholds` only if supported by existing code

Forbidden:

- execution mode and live enablement flags
- replication flags
- neural execution flags
- learning-to-execution flags
- Mode B/C ACKs
- D2/D3/lifecycle governance flags
- Coinbase credentials
- oversell and no-naked-sell guards
- market-order governance flags

## Open-State Safety

Activation blocks when:

- `open_orders > 0`
- `open_positions > 0`
- `open_d3_exit > 0`
- controlled stop/close order is pending
- lifecycle error is active
- full POC readiness is not ready
- Mode C readiness is not ready

## Cooldown And Rate Limit

Activation blocks when:

- cooldown is active
- max changes per 24h is reached
- previous activation is not evaluated
- more than one parameter is included

Defaults are one change per 24 hours and one parameter per activation.

## Backup And Rollback

Before an ACK-gated apply, the governor backs up:

```text
state/approved_parameter_profile.json
```

to:

```text
state/autonomous_parameter_governor/backups/
```

It then writes:

```text
state/autonomous_parameter_governor/rollback_plan_latest.json
state/autonomous_parameter_governor/activations.jsonl
```

Rollback is dry-run by default and requires:

```text
AUTONOMOUS_PARAMETER_GOVERNOR_ROLLBACK_ACK=I_APPROVE_AUTONOMOUS_PARAMETER_GOVERNOR_ROLLBACK
```

## Commands

```bash
python3 tools/show_autonomous_parameter_governor_status.py --json
python3 tools/prepare_autonomous_parameter_activation.py --json
python3 tools/run_autonomous_parameter_governor.py --json
python3 tools/rollback_autonomous_parameter_profile.py --json
python3 tools/write_autonomous_parameter_governor_audit.py --json
```

`run_autonomous_parameter_governor.py` is dry-run unless `--apply` is passed and all env/ACK/safety checks pass.

## Paths

Reports:

```text
reports/autonomous_parameter_governor/governor-status-latest.json
reports/autonomous_parameter_governor/activation-plan-latest.json
reports/autonomous_parameter_governor/activation-plan-latest.md
reports/autonomous_parameter_governor/governor-run-latest.json
reports/audits/autonomous-parameter-governor-latest.json
reports/audits/autonomous-parameter-governor-latest.md
```

Future ACK-gated activation state:

```text
state/autonomous_parameter_governor/activations.jsonl
state/autonomous_parameter_governor/backups/
state/autonomous_parameter_governor/rollback_plan_latest.json
```

## Current Codex Run

This Codex run does not live-activate anything. Current Adaptive Policy candidate is unavailable because `insufficient_market_regimes`, so the governor must report no-op.

Parameter Candidate Analysis may still show calculated effect-size and confidence interval diagnostics for a blocked candidate. The governor must treat those diagnostics as non-activation-eligible while `candidate_available=false` or any higher Adaptive Policy gate fails.

## Reflection/Adaptive Sidecar

The report-only sidecar can refresh reflection persistence, Adaptive Policy Lab, parameter candidate analysis, and governor status outside the trading loop:

```bash
python3 tools/run_reflection_adaptive_report_sidecar.py --json
```

The sidecar writes reports under `reports/sidecars/` and `logs/reflection_adaptive_sidecar.jsonl`. It does not enable the governor, apply profiles, mutate `.env`, mutate live order state, or perform Coinbase actions. Governor activation remains disabled/report-only unless explicitly enabled, exact ACK/hash requirements are met, and all safety gates pass.
