# D.45 Short-Horizon Exit Strategy Options

## Scope

Decision-only report for the active BTC-USDC replacement TP1 order. This report does not cancel, replace, submit, reprice, lifecycle-apply, mutate trading state, restart services or allow learning-to-execution.

## Active Order

| Field | Value |
| --- | --- |
| ticker | `BTC-USDC` |
| client_order_id | `phased4-BTCUSDC-TP1-repl-bc3330fe-20260529064443` |
| exchange_order_id | `6f6fa436-f5b9-4df5-bb23-ddf35a27a56a` |
| linked_position_id | `76310097-849e-481c-b587-ba44bc3330fe` |
| side | `SELL` |
| limit_price | `76000.00` |
| size_base / remaining_size | `0.00006489` |
| latest known lifecycle | `OPEN/open`, zero fills |
| local reservation | `0.00006489` |
| current local route | `open_keep_open / wait_for_trigger` |

Old order `daa5ef77-9967-4fb0-b0c7-4f7c0680b512` at `84800.00` is local `cancelled` with zero fills. The replacement at `76000.00` is the only open exit; reservation is coherent; duplicate/oversell are false.

## Market Distance

Read-only public Coinbase product-book snapshot:

| Field | Value |
| --- | ---: |
| timestamp | `2026-05-29T14:37:14.418290+00:00` |
| best_bid | `72675.30` |
| best_ask | `72675.31` |
| mid_price | `72675.305` |
| source | `/api/v3/brokerage/market/product_book` |

Distance to active `76000.00` target:

| Measure | Value |
| --- | ---: |
| absolute distance vs mid | `3324.695` |
| distance as pct of target | `4.3746%` |
| distance as pct of mid | `4.5747%` |
| D.45 target band | `far_from_target` |
| market trigger | `no` |

Interpretation: `76000.00` is not a near-term trigger under the D.45 trigger policy. Without a fresh ATR/regime report in this decision round, the conservative assumption is that a `4.6%` move from mid is not a reliable short-horizon fill target unless BTC rallies strongly. It may take days, and it may not fill before the operator wants another decision.

## D.5 No-Fill/Stale Metrics

From the local historical report with the snapshot mid:

| Metric | Value |
| --- | ---: |
| no_fill_duration_seconds | about `28356` |
| stale_order_age_seconds | about `28356` |
| target_distance_abs | `3324.695` |
| target_distance_pct | `4.3746%` of target |
| target_distance_band | `far_from_target` |
| no_fill_recommendation_label | `consider_reprice_later` |
| learning_to_execution_allowed | `false` |

D.5 remains report-only. These metrics do not authorize execution or parameter changes.

## Options

| Option | Description | Fill probability | Plan preservation | Realized-loss risk | Churn risk | Safety architecture | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | Keep `76000.00` and wait | Low short-horizon while far from target | Best among live choices | Lower than de-risk choices if it fills | None | Strongest | Operationally safest, but may take days. |
| B | Future closer TP1, e.g. `74500-75000` | Medium | Moderate | Higher than `76000`, lower than near-market | Medium | Requires full D.4 controlled cancel/replace | `74500` is about `2.51%` above mid; `75000` about `3.20%` above mid. Needs future ACK. |
| C | Future near-market de-risk | Highest | Weak; label as de-risk, not TP | Highest | Medium/high | Requires full D.4 controlled cancel/replace | Best if risk reduction matters more than preserving TP. Should not be framed as take-profit. |
| D | Future split-style design | Potentially balanced | Potentially good | Controlled if partial reservations are safe | High implementation risk now | Only if architecture supports partial reservations safely | Not immediate live action unless code/gates prove partial-reservation handling. |
| E | Simulated/fake fill lifecycle test | Not a market fill | N/A | None on live order | None | Strong; temp dirs/fake snapshots | Best if the goal is proving lifecycle handling, not monetizing the open order. |
| F | Controlled micro-position future test | Tests real lifecycle on separate tiny trade | N/A | Small but real | Medium | Must avoid conflict with current reservation | Later only; requires separate entry/exit route and preflight. |
| G | Time-based review policy | No immediate fill impact | Good | None now | Low | Strong | Keep `76000` for N hours, then run decision-only reprice report if still far/no-fill. |

## Risk Table

| Risk | Relevant Options | Control |
| --- | --- | --- |
| Duplicate/oversell or second SELL | B, C, D, F | Full D.45/D.4 preflight; exactly one open exit; coherent reservation; ACK-gated live route only. |
| Chasing price via repeated reprice | B, C | Use a time-boxed review policy; no automatic reprice; require a new decision report before any D.4 route. |
| Unnecessary realized loss | C, possibly B | Label near-market as de-risk; compare against entry and current notional before any future approval. |
| Waiting too long | A, G | Use time-based review, not repeated monitoring. |
| Confusing lifecycle testing with monetization | E, F | Keep simulated fill tests offline; do not mutate real state. |
| Architecture not ready for split reservations | D | Treat as future design unless tests/gates prove partial reservations. |

## Future ACK Requirements

Any future live cancel/replace needs a separate D.4 controlled route, full preflight, and exact operator ACK:

```text
I_UNDERSTAND_AND_APPROVE_D4_TRAILING_CANCEL_REPLACE_ONE_SHOT
```

Any future fill/terminal apply needs the D.3 lifecycle ACK-gated route and real evidence:

```text
I_UNDERSTAND_AND_APPROVE_D3_OPEN_EXIT_LIFECYCLE_APPLY
```

This report does not arm or consume any ACK.

## Recommendation

Recommended next product route: **G + E**.

1. Keep the live `76000.00` order unchanged for a defined time box, such as `4-6 hours`, unless a valid trigger appears first.
2. If still `far_from_target` and zero-fill after that time box, run a decision-only D.4 reprice report comparing keep `76000`, closer recovery target `74500-75000`, and near-market de-risk.
3. In parallel, if the goal is proving lifecycle correctness, run offline fake-snapshot lifecycle tests/reports in temp dirs. Do not use the real order or real state for simulated applies.

Reason: this preserves safety architecture, avoids another immediate reprice/churn cycle, gives the market a bounded chance to move, and separates lifecycle testing from the economic decision of trying to exit faster.

## Do Not Do Now

- Do not cancel/replace again in this round.
- Do not near-market de-risk without a separate explicit de-risk decision and ACK.
- Do not split the live exit unless partial-reservation architecture and gates are proven first.
- Do not lifecycle-apply without real fill or terminal evidence and a separate ACK-gated workflow.
- Do not use D.5 learning output to change execution behavior.

## Code/Test Need Before Acting

No new code is required before choosing A, B, C, E or G as a future operator route. Before any split-style live route, add focused design/tests for partial reservations, duplicate/oversell prevention and post-apply reservation coherence.
