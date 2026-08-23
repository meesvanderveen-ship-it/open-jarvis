# D.6 Fill Realism / Post-Only Assumption Pack v1

Status: research-only scaffold.

## Purpose

`bot/phase_d6_fill_realism_assumptions.py` describes whether local order-candidate or evidence rows have enough context to reason about post-only fill realism.

It is not a live execution model. It does not fetch order books, inspect active orders, recommend prices, rank settings, or approve parameter changes.

## Inputs

- Explicit local JSON or JSONL paths only.
- Intended fixture/source rows:
  - order candidate rows,
  - D.5 evidence rows,
  - local lifecycle event rows,
  - simple local top-of-book snapshots,
  - local regime labels if already attached to rows.

Inputs under `state/` and `.env` paths are rejected by the D.6 research path guard.

## Row Fields

Each `fill_realism_row` may include:

- `product_id`
- `order_label`
- `side`
- `limit_price`
- `reference_bid`
- `reference_ask`
- `spread_pct`
- `distance_to_best_bid_pct`
- `distance_to_best_ask_pct`
- `post_only_crossing_risk`
- `likely_maker`
- `tiny_notional_flag`
- `notional_at_limit`
- `estimated_fee_impact`
- `no_fill_duration_seconds`
- `cancel_replace_count`
- `regime_labels`
- `evidence_categories`
- `parameter_categories_implicated`
- `fill_realism_class`
- `evidence_strength`
- `warnings`
- `blockers`

## Fill Realism Classes

- `likely_unfillable_far_from_market`
- `plausible_maker_near_market`
- `crossing_or_taker_risk`
- `insufficient_orderbook_context`
- `tiny_notional_high_overhead`

These are descriptive classes only. They must not be interpreted as instructions to place, cancel, replace, reprice, or avoid an order.

## CLI

```bash
python3 tools/show_phase_d6_fill_realism_assumptions.py --input /tmp/orders.json --json
```

The CLI prints to stdout only.

## Safety Flags

The report sets:

- `research_only=true`
- `no_coinbase_call=true`
- `no_live_action=true`
- `state_write_performed=false`
- `no_optimization=true`
- `parameter_search_performed=false`
- `parameter_change_allowed=false`
- `learning_to_execution_allowed=false`
- `contains_rankings=false`
- `contains_recommendations=false`
- `contains_live_instructions=false`
- `human_review_required=true`
- `parameter_review_approved=false`

## Limitations

- No queue-position model.
- No empirical fill probability estimate.
- No live fee schedule.
- No parameter sensitivity analysis.
- No parameter proposal or approval.
