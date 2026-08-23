# Neural Shadow Learning

Neural Shadow Policy v1 is a GrowBot-style learning layer for the Coinbase spot bot:

```text
episodes/outcomes -> reward labels -> local shadow policy -> compact prediction -> soft decision context
```

It is deliberately not an execution bridge. Training uses only local logs, state, and reports. It does not call OpenAI, Coinbase, or external APIs, and it does not write parameters or activate approved profiles.

## Data Flow

Local inputs:

```text
state/decision_outcomes.json
logs/decision_outcomes.jsonl
logs/execution_outcomes.jsonl
logs/trade_reflections.jsonl
logs/trade_learning_report.json
reports/live_learning/live-learning-context-latest.json
reports/live_learning/cost-aware-backlearning-latest.json
reports/live_learning/start-parameter-candidates-latest.json
reports/d6/*.json
state/open_orders.json
state/positions.json
```

Dataset outputs:

```text
reports/live_learning/neural-training-dataset-latest.jsonl
reports/live_learning/neural-training-dataset-summary-latest.json
reports/live_learning/neural-reward-summary-latest.json
```

Model/report outputs:

```text
state/neural_shadow_policy.json
reports/live_learning/neural-shadow-policy-latest.json
reports/live_learning/neural-shadow-policy-eval-latest.json
```

Missing numeric features are stored as `null` and encoded as `0.0` for model training. Missing categories become `unknown`; missing booleans become `false`. Corrupt JSONL lines are skipped and counted in the dataset summary.

## Safety Contract

Runtime context is inserted under:

```json
{
  "decision_context": {
    "neural_shadow_policy": {
      "enabled": true,
      "execution_allowed": false,
      "prediction": "prefer_no_trade",
      "confidence": 0.72,
      "top_reasons": []
    }
  }
}
```

The v1 policy is soft context only:

```text
NEURAL_SHADOW_POLICY_ENABLED=true
NEURAL_SHADOW_POLICY_TRAINING_ENABLED=true
NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED=false
NEURAL_SHADOW_POLICY_AGREEMENT_REQUIRED=false
```

`BotConfig.validate()` rejects `NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED=true`. Parameter suggestions are report-only and limited to the approved-profile whitelist. Approved profile activation remains the only parameter activation route.

## One-Class Passivity Guard

As of 2026-06-14 the live dataset is effectively one-class `prefer_no_trade`. That is not balanced execution evidence.

When the loaded model has only one nonzero class:

- Neural Shadow remains `diagnostic_only`.
- A one-class `prefer_no_trade` prediction is capped at `confidence=0.10` for decision context.
- The context explicitly reports `can_block_planner=false`, `can_block_judge=false` and `can_authorize_execution=false`.
- It must not make entry criteria stricter, block planner observability, block final-judge eligibility, block D2/D3, authorize execution, mutate parameters or bridge learning directly into execution.

Balanced labels are required before Neural Shadow can become anything more than audit/context. `NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED=false` remains mandatory.

## Commands

```bash
python3 tools/build_neural_training_dataset.py --json-out reports/live_learning/neural-training-dataset-summary-latest.json

python3 tools/train_neural_shadow_policy.py \
  --dataset reports/live_learning/neural-training-dataset-latest.jsonl \
  --model-out state/neural_shadow_policy.json \
  --report-out reports/live_learning/neural-shadow-policy-latest.json

python3 tools/evaluate_neural_shadow_policy.py \
  --model state/neural_shadow_policy.json \
  --dataset reports/live_learning/neural-training-dataset-latest.jsonl \
  --json-out reports/live_learning/neural-shadow-policy-eval-latest.json

python3 tools/show_neural_shadow_policy_status.py --json
```

With fewer than `NEURAL_SHADOW_POLICY_MIN_SAMPLES` samples, training still writes a compact model and report with `status=insufficient_samples_shadow_only`; execution remains disabled.
