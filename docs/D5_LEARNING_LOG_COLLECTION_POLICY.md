# D.5 Learning Log Collection Policy + Export Workflow v1

## Scope

This policy turns the D.5 structured learning-log foundation into a practical report-only collection workflow. It defines when to create learning events, what event set is worth reviewing, how to export JSONL, and how to keep learning fully separated from execution.

The active `BTC-USDC` TP1 replacement at `76000.00` remains untouched. This policy does not call Coinbase, submit, cancel, replace, reprice, lifecycle-apply, write trading state, restart services, mutate `.env`, enable learning-to-execution or change strategy/execution parameters.

## Event Types

Use these event types with `tools/show_phase_d5_learning_log.py --event-type ...`:

| Event type | Use when |
| --- | --- |
| `open_no_fill_observation` | Meaningful triggered operator cycle shows open/no-fill, stale age or target-distance context. |
| `partial_fill_observation` | PARTIAL evidence exists from a read-only lifecycle poll or fixture report. |
| `filled_observation` | FILLED evidence exists and can be summarized from lifecycle/D.5 reports. |
| `terminal_observation` | CANCELLED, EXPIRED or REJECTED terminal evidence exists. |
| `reprice_decision_observation` | A decision-only reprice report compares keep/reprice/de-risk options. |
| `cancel_replace_observation` | A controlled cancel/replace attempt/result is documented. |
| `safety_drift_observation` | P0 drift, duplicate exit, reservation mismatch, oversell or uncertain lifecycle evidence appears. |
| `operator_decision_observation` | Operator chooses wait, reprice-review later, keep current order, or another non-executing route. |

Do not emit learning events for noisy identical `OPEN/open keep_open` checks unless a valid trigger made the observation meaningful.

## When To Collect

Create one event after each meaningful report/checkpoint:

- after each trigger-aware operator cycle;
- after any read-only lifecycle poll;
- after any D.4 reprice decision report;
- after any controlled cancel/replace result;
- after any PARTIAL, FILLED, CANCELLED, EXPIRED or REJECTED evidence;
- after any P0 safety drift or fail-closed lifecycle uncertainty;
- after an explicit operator decision that changes future review posture.

Do not collect just because time passed. If the trigger policy says no poll/no action, log only when the decision itself is useful for later review, such as a bounded review-window decision or stale/no-fill checkpoint.

## Minimum Review Window

Run a future Codex parameter-review task only after enough signal exists. Recommended minimum:

- time window: at least `3-7 days` of meaningful observations, or
- event count: at least `10-25` meaningful events, and
- diversity: include at least two of these groups:
  - open/no-fill or stale observations;
  - reprice decision observations;
  - fill/partial/terminal observations;
  - cancel/replace outcome observations;
  - safety drift observations.

If there are fewer than `10` meaningful events and no fill/terminal evidence, use the log only for operational audit, not parameter tuning.

## Export Workflow

Use explicit fixture/report inputs. Safe export locations are operator-selected paths outside trading state, for example:

- `/tmp/coinbase_bot_learning_exports/...`
- `docs/reports/...` if the operator explicitly wants a checked-in report artifact

Do not write exports into:

- `state/`
- `.env` or env-derived paths
- service/runtime files
- live order or position stores

Example JSONL export from fixture/report files:

```bash
python3 tools/show_phase_d5_learning_log.py \
  --lifecycle-fixture /tmp/d5_inputs/lifecycle.json \
  --d5-metrics-fixture /tmp/d5_inputs/d5_metrics.json \
  --d45-fixture /tmp/d5_inputs/d45_exit_operations.json \
  --d4-decision-fixture /tmp/d5_inputs/d4_decision.json \
  --event-type open_no_fill_observation \
  --operator-decision wait_for_trigger \
  --source trigger_aware_operator_cycle \
  --window-start 2026-05-29T00:00:00Z \
  --window-end 2026-05-29T23:59:59Z \
  --jsonl \
  --output /tmp/coinbase_bot_learning_exports/d5_learning_20260529.jsonl
```

For stdout-only review:

```bash
python3 tools/show_phase_d5_learning_log.py \
  --lifecycle-fixture lifecycle.json \
  --d5-metrics-fixture d5_metrics.json \
  --d45-fixture d45_exit_operations.json \
  --event-type operator_decision_observation \
  --operator-decision keep_76000_wait_for_trigger \
  --jsonl
```

The exporter reads only the provided files. It performs no Coinbase call and no trading-state write.

## Feeding Codex Later

A future parameter-review prompt should provide:

- the exported JSONL file or its relevant contents;
- the review window start/end;
- a count by event type;
- any known missing evidence;
- explicit instruction that the task is decision-only.

The review may produce recommendations such as target-band threshold changes, stale-window changes, reprice-review cadence changes or additional tests. It must not apply them.

## Execution Boundary

Learning collection is not execution.

Hard gates remain:

- `learning_to_execution_allowed=false`
- `parameter_change_allowed=false`
- `report_only=true`

Any future parameter change requires:

1. a separate Codex parameter-review prompt;
2. a proposed diff or config change;
3. focused tests and relevant regression tests;
4. explicit human approval;
5. a separate apply/merge step.

Learning-to-execution remains disabled until a separately designed, tested and approved execution gate exists.

## Stop Conditions

Stop collection/export work if it would require:

- Coinbase polling or any Coinbase write;
- live cancel/replace/submit/reprice;
- lifecycle apply;
- writing `state/open_orders.json`, `state/positions.json` or `.env`;
- service restart;
- automatic parameter mutation;
- using the active `76000.00` order as anything other than read-only report context.

