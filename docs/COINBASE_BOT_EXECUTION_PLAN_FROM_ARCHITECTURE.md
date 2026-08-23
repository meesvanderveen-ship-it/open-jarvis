# Coinbase bot execution plan from architecture

## 1. Current state

De huidige fase is D.3 controlled live exit lifecycle governance met exact één open TP1 SELL voor `BTC-USDC`.

De actuele branch is:

- `OPEN/open`
- `filled_base=0`
- `filled_quote=0`
- `fill_count=0`
- `keep_open`
- geen cancel-candidate
- geen replace-candidate

Dit betekent operationeel:

- geen nieuwe live action
- geen apply
- geen tweede SELL
- geen cancel/replace
- geen retry
- alleen read-only planning en documentatie zijn nu veilig

## 2. Hard freeze while current D.3 TP1 order is OPEN/open

Zolang de huidige D.3 TP1-order `OPEN/open keep_open` blijft, geldt een harde freeze op alle lifecycle-mutaties en alle nieuwe live-execution branches.

Concreet:

- de open TP1 lifecycle blijft leidend
- de eerstvolgende toegestane operationele stap is: later opnieuw een read-only statuscheck doen
- alle vervolgbranches wachten tot een echte statuswijziging of een expliciete governance-candidate ontstaat
- onzekerheid moet fail-closed behandeld worden

## 3. P0 — Current D.3 TP1 lifecycle

Doel: de huidige lifecycle veilig uitlopen zonder premature actie.

Taken:

- respecteer `OPEN/open -> keep_open`
- geen monitorloop of bundeling met andere acties
- bij een later moment alleen read-only:
  - snapshot
  - reconcile dry-run
  - governance previews
- operationele branch pas wijzigen als één van deze situaties ontstaat:
  - `PARTIAL`
  - `FILLED`
  - `CANCELLED`
  - `EXPIRED`
  - `REJECTED`
  - expliciete `cancel_candidate`
  - expliciete `replace_candidate`

Stopconditie:

- zolang status `OPEN/open keep_open` blijft: niets toepassen

## 4. P1 — Reconcile/apply branches after status change

Deze tak wordt pas actief na een echte statuswijziging buiten de normale `OPEN/open keep_open` branch.

### PARTIAL

- eerst snapshot + reconcile dry-run
- controleer:
  - `filled_base`
  - `filled_quote`
  - `avg_fill_price`
  - `remaining_size`
  - `fees`
  - `position_size_base`
  - `bot_managed_base`
  - `reserved_base_open_exit_orders`
- apply alleen met:
  - `I_UNDERSTAND_AND_APPROVE_D3_LIVE_EXIT_RECONCILIATION_APPLY`
- daarna alleen D.2/D.3 preview-only

### FILLED

- eerst snapshot + reconcile dry-run
- controleer:
  - full TP1 completion
  - reservation release
  - position/base update
- apply alleen met D.3 reconciliation ACK
- daarna D.2 status read-only
- daarna TP2/runner alleen preview-only

### CANCELLED / EXPIRED / REJECTED

- eerst snapshot + reconcile dry-run
- controleer:
  - closeout / reject proposal
  - reservation release
  - positiecoherentie
- geen nieuwe SELL vóór coherente closeout
- apply alleen met D.3 reconciliation ACK

## 5. P1 — Safety checks before any future live action

Vóór een volgende live SELL-, cancel- of replace-pilot moeten deze safety-routes expliciet geborgd zijn:

- central live-exit gate moet leidend blijven voor alle SELL-routes
- legacy SELL-routes moeten geblokkeerd blijven buiten D.3 gates
- duplicate exit protection moet groen blijven
- no-oversell / no-negative-base invariants moeten aantoonbaar groen blijven
- `OPEN/open` mag geen state mutation veroorzaken
- pre-apply state snapshot moet vóór elke ACK-mutation beschikbaar zijn
- replication/follower lifecycle moet geïsoleerd blijven
- Coinbase product-rules gating moet aantoonbaar kloppen:
  - base increment
  - quote increment
  - min order quote
  - min base size
  - rounded sell base
  - estimated quote
- partial-fill edgecases moeten gedekt blijven:
  - multiple fills
  - fees
  - avg_fill_price
  - dust
  - remaining size onder minimum
  - partial reservation release
- na elke lifecycle change moet D.2/D.3 fingerprint en live-rule coherence opnieuw read-only gevalideerd worden

## 6. P2 — D.3 continuation after coherent fill/closeout

Pas na coherente D.3 apply of closeout:

- D.2 position status opnieuw read-only controleren
- TP2/runner alleen preview-only
- nieuwe D.3 preview alleen na coherente base/reservation state
- nieuwe fingerprint review uitvoeren
- geen nieuwe SELL zonder aparte expliciete approval

Dit is dus vervolg op D.3 afronding, niet parallel daaraan.

## 7. P2 — Controlled cancel-only branch if candidate appears

Deze branch is alleen toegestaan als governance expliciet naar een cancel-candidate schuift of cancel-first nodig wordt.

Volgorde:

1. controlled cancel-only preflight
2. aparte cancel-ACK
3. Coinbase-status moet eerst `CANCELLED` worden
4. local closeout dry-run
5. local closeout apply alleen met D.3 reconciliation ACK
6. daarna nieuwe D.3 preview
7. daarna fingerprint review

Belangrijk:

- geen atomic cancel+replace
- geen replace in dezelfde stap
- geen nieuwe SELL vóór coherente closeout

## 8. P3 — D.4 cancel/replace/trailing design

D.4 hoort pas te starten na afronding van de huidige open lifecycle.

Ontwerp- en testonderwerpen:

- trailing activation
- trailing distance
- stale-order logic
- concrete cancel/replace thresholds
- no atomic cancel+replace
- cancel-first sequencing
- reservation-aware replacement
- duplicate-exit guard
- min-size / min-quote / product-rules gating
- post-apply sanity checklist
- logging / observability checklist

Eerst design en read-only tests. Pas daarna eventueel een controlled pilot.

## 9. P4 — D.5 execution learning

D.5 komt pas na complete exit lifecycle events.

Benodigde inputs:

- fill latency
- maker/taker result
- slippage
- stale-open duration
- cancel/replace decision quality
- realized net edge

Belangrijke gate:

- learning mag nooit direct live execution beïnvloeden zonder aparte expliciete execution gate

## 10. Safe preparatory tasks allowed now

Deze taken kunnen veilig vóór een statuswijziging:

- documentatie aanscherpen
- architecture/roadmap/planning verder structureren
- read-only audits van functiebehoud en safety-routes
- read-only testinventarisatie
- ontwerp van D.4-documentatie en testmatrix voorbereiden
- checklist opstellen voor D.3 PARTIAL/FILLED/CANCELLED/EXPIRED/REJECTED branches
- checklist opstellen voor pre-apply snapshots en post-apply sanitychecks
- mapping van legacy SELL-routes en gate coverage documenteren
- replication/follower isolation review plannen
- observability/logging checklist opstellen

## 11. Forbidden tasks while OPEN/open

- live statuscheck als daar niet expliciet om gevraagd is
- Coinbase call
- live BUY
- tweede SELL
- retry
- cancel
- replace
- reconcile apply
- recovery apply
- service restart
- `.env`-mutatie
- state mutation
- ACK-gebruik
- new preview-submit bundelen met lifecycle-mutation
- follower/replication lifecycle activeren

## 12. Recommended next Codex prompt

Aanbevolen volgende prompt:

"Werk planning-only verder aan D.3/D.4 readiness. Lees eerst de vier contextdocumenten. Doe alleen read-only repo-inspectie. Maak daarna een test- en safety-matrix voor:

- D.3 PARTIAL/FILLED/CANCELLED/EXPIRED/REJECTED reconcile branches
- central live-exit gate coverage
- duplicate/no-oversell invariants
- pre-apply snapshot discipline
- cancel-first governance voor latere D.4

Geen live statuscheck, geen Coinbase call, geen codepatch buiten docs/tests-planning, geen state mutation."
