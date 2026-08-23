# D.4 Reprice Decision

## Purpose

Decision-only preparation for the active BTC-USDC D.3 TP1 SELL. This document compares keeping the current `84800.00` TP1 against controlled reprice candidates. It does not authorize cancel, replace, submit, lifecycle apply, state mutation, parameter changes or learning-to-execution.

## Current State

Local D.45 sanity was checked first:

- `order_found=true`
- `lifecycle_branch=open_keep_open`
- `recommended_operator_action=wait_for_trigger`
- `reserved_base_open_exit_orders=0.00006489`
- `blockers=[]`
- `fill_count=0`
- `filled_base=0`
- `no_coinbase_call=true`
- `no_live_action=true`
- `state_write_performed=false`
- `learning_to_execution_allowed=false`

Active order:

| Field | Value |
| --- | --- |
| ticker | `BTC-USDC` |
| client_order_id | `phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000` |
| exchange_order_id | `daa5ef77-9967-4fb0-b0c7-4f7c0680b512` |
| linked_position_id | `76310097-849e-481c-b587-ba44bc3330fe` |
| side / label | `SELL` / `TP1` |
| size_base / remaining_size | `0.00006489` / `0.00006489` |
| current limit | `84800.00` |
| reservation | `0.00006489` |

Latest read-only lifecycle evidence from the prior trigger-aware cycle remained `OPEN/open` with zero fills and `keep_open`.

## Market Snapshot

One current read-only Coinbase public product-book snapshot was fetched for option math.

| Field | Value |
| --- | --- |
| source | `/api/v3/brokerage/market/product_book` |
| auth_required | `false` |
| time | `2026-05-29T06:16:39.880524Z` |
| best_bid | `73624.55` |
| best_ask | `73624.56` |
| mid_price | `73624.555` |

Sandbox fetch could not use the public fallback because the client later fell through to an authenticated endpoint without API env. A single escalated read-only public fetch succeeded. No write endpoint was used.

## Option Table

Size used: `0.00006489` BTC. Current `84800.00` quote value is `5.50267200` USDC. Entry reference `80000.00` quote value is `5.19120000` USDC.

| Option | Type | Target | Distance vs mid | Est. quote | Delta vs current 84800 quote | Est. vs 80000 entry quote | Post-only feasible | Fill probability | Future route |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| A | keep current TP1 | `84800.00` | `+11175.44` / `+15.1790%` | `5.50267200` | `0.00000000` | `+0.31147200` | yes | `unlikely_short_term` | no action |
| B | plan-preserving | `82000.00` | `+8375.44` / `+11.3759%` | `5.32098000` | `-0.18169200` | `+0.12978000` | yes | `unlikely_short_term` | D.4 controlled cancel/replace required |
| C | recovery target | `78000.00` | `+4375.44` / `+5.9429%` | `5.06142000` | `-0.44125200` | `-0.12978000` | yes | `moderate` | D.4 controlled cancel/replace required |
| D | faster recovery | `76000.00` | `+2375.44` / `+3.2264%` | `4.93164000` | `-0.57103200` | `-0.25956000` | yes | `short` | D.4 controlled cancel/replace required |
| E | near-market de-risk | `73624.57` | `+0.02` / `+0.0000%` | `4.77749835` | `-0.72517365` | `-0.41370165` | yes | `near` | D.4 controlled cancel/replace required |

Trade-offs:

- A preserves the original upside but conflicts with the operator context of not waiting months.
- B preserves a positive result versus `80000.00` entry reference but remains far from market.
- C reduces wait materially versus B, but still needs about a `5.94%` recovery.
- D gives a realistic short-horizon recovery target without taking immediate near-market de-risk.
- E maximizes fill probability but is explicitly de-risk/loss-control, not a TP.

## Recommendation

Recommended option: `reprice 76000`.

Why:

- The operator explicitly does not want to wait months.
- `84800` and `82000` remain too far from current mid for a short-horizon exit.
- `78000` is a reasonable recovery target, but still requires almost `6%` upside from current mid.
- `76000` requires about `3.23%` upside, making it a more realistic short-horizon exit while avoiding a blind near-market de-risk.
- The order size is small, so the absolute USDC trade-off versus the current TP is limited, but leaving a far-away order open carries opportunity-cost and operational drag.

Residual risks:

- `76000` is below the `80000` entry reference, so it is a controlled recovery/de-risk reprice rather than a true take-profit.
- If BTC rebounds sharply, `76000` may exit before higher recovery targets.
- If BTC continues down, even `76000` may not fill quickly.
- Any reprice requires cancel-first replacement and future ACK; this report does not execute it.

## Why No Live Action Now

This round is decision-only. It did not cancel the current order, did not submit a replacement, did not apply lifecycle evidence and did not mutate trading state.

## Exact Next Prompt

Use this next prompt if the operator chooses to execute the recommended reprice:

```text
D.4 Controlled Cancel/Replace
```

Operator choice to carry forward:

```text
I choose D.4 reprice BTC-USDC TP1 to 76000.00, cancel-first, replacement only after confirmed cancel.
```

Required future ACK:

```text
I_UNDERSTAND_AND_APPROVE_D4_TRAILING_CANCEL_REPLACE_ONE_SHOT
```

If using the older D.3 controlled reprice path instead, the required ACK is:

```text
I_UNDERSTAND_AND_APPROVE_D3_CANCEL_REPLACE_REPRICE_ONE_SHOT
```

## Safety Confirmation

- Coinbase write calls: `no`
- live action: `no`
- cancel/replace/submit: `no`
- lifecycle apply: `no`
- trading-state write: `no`
- service restart: `no`
- `.env` mutation: `no`
- dependency changes: `no`
- learning-to-execution: `no`
