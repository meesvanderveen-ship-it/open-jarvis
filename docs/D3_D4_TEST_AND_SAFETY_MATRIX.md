# D.3 / D.4 test and safety matrix

## 1. Purpose

Deze matrix is bedoeld voor:

- veilige afronding van de huidige D.3 open TP1 lifecycle
- expliciete voorbereiding op D.4 cancel/replace/trailing
- structurering van test- en safetydekking vóór verdere live acties

Deze matrix is geen toestemming voor live acties.

## 2. Current freeze

- de huidige open D.3 TP1 order blijft leidend
- actuele branch: `OPEN/open keep_open`
- huidige open order:
  - `ticker=BTC-USDC`
  - `client_order_id=phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000`
  - `exchange_order_id=bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31`
  - `linked_position_id=76310097-849e-481c-b587-ba44bc3330fe`
- geen live action zolang de branch niet wijzigt
- geen apply/cancel/replace zolang `OPEN/open keep_open` geldt

## 3. D.3 reconcile branch tests

| scenario | expected dry-run action | required checks | apply allowed? | ACK required? | forbidden actions | expected post-condition | existing tests/files if known | missing tests/gaps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `OPEN/open keep_open` | `keep_open`, no state write | snapshot status, local order match, `filled_base=0`, `filled_quote=0`, `remaining_size`, linked position, duplicate-open check | nee | n.v.t. | apply, cancel, replace, retry, tweede SELL | local state ongewijzigd, reservation blijft open, branch blijft `keep_open` | `tests/test_phase_d3_live_exit_reconciliation.py`, `tools/reconcile_phase_d3_live_exit_order.py`, `tools/show_phase_d3_live_exit_order_snapshot.py` | expliciete testmatrix-koppeling met post-apply sanitycheck ontbreekt |
| `PARTIAL` | partial reconcile dry-run, fill delta proposal | `filled_base`, `filled_quote`, `avg_fill_price`, `fees`, `remaining_size`, `position_size_base`, `bot_managed_base`, reserved base this exit, reserved base other exits | ja, maar alleen in aparte sessie | ja, `I_UNDERSTAND_AND_APPROVE_D3_LIVE_EXIT_RECONCILIATION_APPLY` | nieuwe SELL, cancel, replace, recovery apply | only delta verwerkt, partial reservation coherent, position blijft open, D.2/D.3 daarna preview-only | `tests/test_phase_d3_live_exit_reconciliation.py` | extra edgecases voor meerdere partial fills, fee-delta, dust-restant, min-size na partial explicieter maken |
| `FILLED` | filled reconcile dry-run, finalization + reservation release proposal | full fill evidence, `filled_base`, `filled_quote`, `avg_fill_price`, `fees`, `remaining_size=0`, total-managed-base semantics, linked position coherence | ja, maar alleen in aparte sessie | ja | nieuwe SELL, cancel, replace, retry | order final, reservation vrijgegeven, position/base coherent gereduceerd, daarna alleen D.2/D.3 preview-only | `tests/test_phase_d3_live_exit_reconciliation.py` | extra test op full fill met available-vs-reserved semantics en post-apply fingerprint revalidation ontbreekt |
| `CANCELLED` | closeout/release dry-run | final status evidence, reservation release proposal, order/position linkage, no duplicate exits | ja, maar alleen in aparte sessie | ja | nieuwe SELL, replace, retry | order final cancelled, reservation vrijgegeven, positie coherent open of resterend | `tests/test_phase_d3_live_exit_reconciliation.py` | expliciete test op post-cancel D.3 preview/fingerprint vervolg ontbreekt |
| `EXPIRED` | closeout/release dry-run | final status evidence, reservation release proposal, order/position linkage | ja, maar alleen in aparte sessie | ja | nieuwe SELL, replace, retry | order final expired, reservation vrijgegeven, positie coherent | `tests/test_phase_d3_live_exit_reconciliation.py` | expliciete test op expiry + stale-open governance handoff ontbreekt |
| `REJECTED` | reject closeout dry-run | reject evidence, no filled delta, reservation release proposal, local order match | ja, maar alleen in aparte sessie | ja | retry, tweede SELL, cancel/replace | order final rejected, reservation vrijgegeven, positie coherent ongewijzigd | `tests/test_phase_d3_live_exit_reconciliation.py`, `tests/test_phase_d3_rejected_submit_cleanup.py`, `bot/phase_d3_rejected_submit_cleanup.py` | expliciete test op reject na al bestaande open lifecycle-context ontbreekt |
| `UNKNOWN/network failure` | block / `unknown_no_apply` / fail-closed | `coinbase_call_succeeded=false`, unsupported or unknown status, geen inferentie uit netwerkfout | nee | n.v.t. | apply, cancel, replace, retry, nieuwe SELL | geen state write, diagnose-only, later exact dezelfde read-only check herhalen | `tests/test_phase_d3_live_exit_reconciliation.py`, `tools/show_phase_d3_live_exit_order_snapshot.py`, `docs/COINBASE_BOT_ARCHITECTURE_AND_FUNCTIONS.md` | expliciete integratietest op sandbox DNS/runtime failure als niet-trading-signal ontbreekt |

## 4. D.3 safety invariant tests

| invariant | scope / expectation | existing tests/files if known | missing tests/gaps |
| --- | --- | --- | --- |
| no duplicate exit | nooit twee open D.3 exits voor dezelfde positie + actie/label | `tests/test_phase_d3_controlled_live_exits.py`, `tests/test_phase_d3_live_exit_reconciliation.py`, `bot/order_store.py` | extra test op duplicate detection na PARTIAL/FILLED closeout vervolg |
| no oversell | `sell_base <= available/unreserved base`; reduce-only lokaal afgedwongen | `tests/test_phase_d3_controlled_live_exits.py`, `bot/phase_d3_controlled_live_exits.py` | extra test op oversell na open-hold semantics en partial apply |
| no negative base | resulting available en managed base mogen niet negatief worden | `tests/test_phase_d3_live_exit_reconciliation.py`, `bot/phase_d3_live_exit_reconciliation.py` | expliciete matrix-test op alle final branches + dust edgecase |
| reservation release | bij FILLED/CANCELLED/EXPIRED/REJECTED moet reservation coherent vrijgegeven worden | `tests/test_phase_d3_live_exit_reconciliation.py`, `tests/test_phase_d3_reservation_governance.py` | aparte test op closeout + open order counts + reservation state samen |
| partial reservation handling | bij PARTIAL blijft alleen resterende reservation open | `tests/test_phase_d3_live_exit_reconciliation.py` | extra tests voor meerdere fills en partial reservation release over meerdere cycles |
| dust / remaining below minimum | remaining/restbase onder minimum moet fail-closed en coherent verwerkt worden | `tests/test_phase_d2_position_executor.py`, `tests/test_phase_c43_tiny_residual_recovery.py` | expliciete D.3 partial/final dust-tests ontbreken nog |
| product rules increment / min quote | base/price/quote increments en `min_order_quote` correct toegepast | `tests/test_phase_d3_controlled_live_exits.py`, `tests/test_phase_d3_controlled_exit_pilot.py`, `tools/show_coinbase_product_rules.py` | expliciete reconcile-tests waarbij remaining size onder increment/min quote zakt ontbreken |
| linked position consistency | ticker / `linked_position_id` / local order / position moeten matchen | `tests/test_phase_d3_live_exit_reconciliation.py` | extra tests op mismatchende position lineage over cancel-first vervolg |
| D.2 fingerprint revalidation | na lifecycle change moet nieuwe preview/fingerprint coherent zijn | `tests/test_phase_d2_position_executor.py`, `tests/test_phase_d3_controlled_exit_pilot.py` | expliciete post-apply fingerprint revalidation flow nog niet als aparte testset aanwezig |
| central live-exit gate | elke live SELL-route moet door de centrale gate | `tests/test_live_exit_gate.py`, `tests/test_coinbase_executor_live_exit_gate.py`, `tests/test_strategy_engine_live_exit_gate.py`, `bot/live_exit_gate.py` | matrixkoppeling naar alle latere D.4 flows documenteren |
| legacy SELL-route blocked | oude SELL-routes mogen niet ongemerkt om de D.3 gate heen | `tests/test_strategy_engine_live_exit_gate.py`, `tests/test_coinbase_executor_live_exit_gate.py`, `tools/show_function_preservation_audit.py` | expliciete auditlijst met alle SELL entrypoints als matrixartifact ontbreekt |
| replication / follower isolation | follower mag master lifecycle niet overnemen | `tests/test_phase_c43_one_entry_smoke_test.py`, `tests/test_phase_d3_controlled_exit_pilot.py`, `tools/show_function_preservation_audit.py` | expliciete D.3 reconcile/cancel-first matrix-test met replication enabled blockers ontbreekt |
| state mutation blocked at `OPEN/open` | `OPEN/open` branch mag niets muteren | `tests/test_phase_d3_live_exit_reconciliation.py`, `tests/test_phase_c44_poll_to_apply_closeout.py` | extra end-to-end dry-run assertion over open order + positions + counts samen ontbreekt |

## 5. Pre-apply snapshot checklist

- snapshot van `state/open_orders.json`
- snapshot van `state/positions.json`
- relevante logs:
  - `logs/order_events.jsonl`
  - `logs/live_exit_orders.jsonl`
  - `logs/phase_d2_position_executor.jsonl`
- actuele live/read-only snapshot van de D.3 order
- reconcile dry-run output
- actuele D.2 report
- actuele D.3 report
- audit output van `tools/show_function_preservation_audit.py`
- `client_order_id`, `exchange_order_id` en `linked_position_id`

## 6. Post-apply sanity checklist

- audit ok
- order status coherent
- position base coherent
- `bot_managed_base` coherent
- `reserved_base` coherent
- no duplicate exits
- no negative base
- open order counts coherent
- D.2/D.3 daarna alleen preview-only
- docs checkpoint updated

## 7. D.4 readiness matrix

| feature | design needed | tests needed | live risk | dependency | allowed before current lifecycle done? | notes |
| --- | --- | --- | --- | --- | --- | --- |
| stale-order thresholds | ja | ja | medium | huidige stale-open observability | ja, alleen design | thresholds moeten expliciet en reproduceerbaar worden |
| cancel-candidate criteria | ja | ja | high | stale-order metrics + reservation semantics | ja, alleen design | candidate mag niet automatisch cancel triggeren |
| replace-candidate criteria | ja | ja | high | cancel-first governance + new preview rules | ja, alleen design | replace nooit direct of atomisch |
| cancel-first sequence | ja | ja | high | D.3 closeout/reconcile ACK flow | ja, alleen design | sequence moet exact zijn: cancel -> poll -> closeout -> new preview |
| no atomic cancel+replace | ja | ja | high | governance and tooling separation | ja, alleen design | harde invariant |
| reservation-aware replacement | ja | ja | high | reservation governance + open-hold semantics | ja, alleen design | replacement mag pas na coherente release |
| trailing activation | ja | ja | medium/high | D.2 runner semantics | nee, niet operationeel | D.4 na huidige lifecycle |
| trailing distance | ja | ja | medium/high | D.2 runner semantics + product rules | nee, niet operationeel | moet fail-closed zijn |
| product-rules gating | deels al aanwezig, verder uitwerken | ja | high | `show_coinbase_product_rules`, live-context preview | ja, alleen design | ook voor replacement rounding |
| duplicate-exit guard | al aanwezig, uitbreiden voor D.4 | ja | high | `OrderStore`, D.3 guards | ja, alleen design | replacement mag geen tweede live exit openen |
| min-size / min-quote | deels aanwezig, uitbreiden voor D.4 | ja | medium/high | product rules + reservation deltas | ja, alleen design | vooral relevant na partials en replacements |
| logging / observability | ja | ja | medium | existing logs/audit | ja, alleen design | nodig voor cancel-first pilot review |
| controlled pilot criteria | ja | ja | high | alle bovenstaande gates + docs/runbook | nee, niet operationeel | pas na huidige lifecycle en expliciete approval |

## 8. What may be tested now

Alleen:

- read-only repo/test inventory
- documentation/test planning
- pure unit-test design
- no live client tests
- no state mutation

## 9. What must wait

- any live cancel
- any live replace
- any apply
- any new SELL
- any D.4 live pilot
- any learning-to-execution

## 10. Recommended next step after matrix

De veiligste volgende stap is:

- read-only test inventory verder mappen op deze matrix
- bestaande tests clusteren per D.3 reconcile branch, invariant en D.4 design dependency
- geen live statuscheck tenzij later tijdstip, duidelijke marktbeweging of echte statuswijziging daarom vraagt
