# D.4 Trailing Preview Scaffold

Timestamp: `2026-05-29`

## Purpose

This scaffold evaluates whether an open D.3 TP1 SELL could theoretically become a D.4 trailing/cancel-replace candidate. It is preview-only: it never calls Coinbase, never cancels, never replaces, never submits, never applies lifecycle evidence and never writes trading state.

The active D.3 order remains `BTC-USDC` TP1 `phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000` / `daa5ef77-9967-4fb0-b0c7-4f7c0680b512`, latest branch `OPEN/open keep_open`, zero fills.

## Inputs

- `ticker`
- `linked_position_id`
- current open D.3 exit order
- position snapshot with `position_size_base` and `reserved_base_open_exit_orders`
- market snapshot fixture:
  - `best_bid`
  - `best_ask`
  - `mid_price`
  - `timestamp`
- product rules fixture:
  - `base_increment`
  - `price_increment`
  - `min_order_quote`
- policy fixture:
  - `activation_price` or `activation_pct`
  - `trailing_distance_pct`
  - `refresh_tolerance_pct`
  - `cooldown_seconds`
  - `stale_book_seconds`
- optional `prior_peak_price`
- optional `cooldown_until`
- optional market-path list for tests, evaluated in memory only

## Outputs

- `status`
- `ticker`
- `linked_position_id`
- `current_order_id`
- `current_exit_price`
- `current_market_mid`
- `activation_state`
- `peak_reference_price`
- `trailing_distance`
- `trailing_stop_price`
- `proposed_replacement_price`
- `proposed_action`: `keep_open`, `preview_reprice_candidate`, or `blocked`
- `reason`
- `blockers`
- `warnings`
- `no_coinbase_call=true`
- `no_live_action=true`
- `state_write_performed=false`
- `cancel_replace_allowed=false`
- `requires_future_ack=true` only when a replacement candidate is suggested

## Safety Blockers

- no open D.3 exit order
- duplicate open D.3 exits for the same linked position
- current order not `SELL`
- current order not `submitted` or `open`
- current order has fills, which must route through D.3 lifecycle first
- reserved base is less than the open exit size
- invalid or stale market snapshot
- cooldown active
- missing activation policy
- missing trailing distance policy
- candidate below `min_order_quote`
- candidate crosses or touches the book and is post-only unsafe

## Test Matrix

| Scenario | Expected result |
| --- | --- |
| price far below activation | `keep_open`, inactive, no candidate |
| below-activation market path | `keep_open`, inactive, no candidate across all steps |
| price above activation | active, peak/reference recorded, no candidate until trigger |
| activation then continued rise | active, peak/reference increases, `keep_open` |
| activation then small pullback | active, within trailing distance, `keep_open` |
| small drift inside refresh tolerance | `keep_open` |
| price falls enough after peak | `preview_reprice_candidate`, future ACK required |
| gap down through trailing stop | preview candidate or blocked with explicit reason; no live action |
| candidate below min quote | blocked |
| product-rule rounding | proposed candidate respects `price_increment` |
| candidate crosses book | blocked |
| stale book during trigger | blocked, no candidate |
| stale snapshot | blocked |
| cooldown active | blocked |
| repeated candidate inside cooldown | blocked |
| duplicate open D.3 exits | P0 blocked |
| reserved-base mismatch | P0 oversell blocked |
| CLI preview with fixtures | no Coinbase call, no live action, no state write |

## Next Step

Keep this scaffold offline until the current D.3 lifecycle is no longer `OPEN/open keep_open` and an operator explicitly asks for a future D.4 design step. The next safe product step is to maintain tests and, if needed, add more fake market-path fixtures.
