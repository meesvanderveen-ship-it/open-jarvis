# Coinbase bot total roadmap from current D.3 open-exit lifecycle

## Fase 0 — Huidige freeze/safety-context

- Er staat exact één open D.3 TP1 live SELL-order voor `BTC-USDC`.
- De actuele operationele branch is `OPEN/open keep_open`.
- Zolang deze lifecycle open staat, zijn live BUY, tweede SELL, retry, cancel, replace, reconcile apply, recovery apply, service restart, `.env`-mutatie en state mutation verboden zonder aparte expliciete menselijke toestemming.
- Verdergaan mag pas als:
  - de orderstatus wijzigt, of
  - governance expliciet naar een candidate-branch schuift, of
  - een latere read-only statuscheck opnieuw bevestigt dat `keep_open` nog steeds geldt.

## Fase 1 — Current open TP1 lifecycle afronden

### A. OPEN/open blijft

- `keep_open` respecteren.
- Niet loop-monitoren.
- Alleen periodiek opnieuw read-only checken bij:
  - later tijdstip
  - duidelijke marktbeweging
  - statuswijziging

### B. PARTIAL

- Eerst snapshot + reconcile dry-run.
- Controleer:
  - `filled_base`
  - `filled_quote`
  - `avg_fill_price`
  - `remaining_size`
  - `fees`
  - `position_size_base`
  - `bot_managed_base`
  - `reserved_base_open_exit_orders`
- Geen apply zonder expliciete reconciliation ACK.

### C. FILLED

- Eerst snapshot + reconcile dry-run.
- Controleer:
  - full TP1 completion
  - position/base update
  - reservation release
- Apply pas met expliciete reconciliation ACK.
- Daarna pas naar D.2/D.3 vervolg.

### D. CANCELLED / EXPIRED / REJECTED

- Eerst snapshot + reconcile dry-run.
- Controleer:
  - closeout / reject proposal
  - reservation release
  - positiecoherentie
- Geen nieuwe SELL vóór coherente local closeout.
- Apply pas met expliciete reconciliation ACK.

### E. cancel/replace candidate

- Geen atomic replace.
- Eerst controlled cancel-only.
- Daarna poll tot `CANCELLED`.
- Daarna closeout.
- Daarna nieuwe D.3 preview en fingerprint review.

## Fase 2 — Reconcile apply-fase na statuswijziging

- Apply is pas toegestaan nadat de live order niet meer in de normale `OPEN/open keep_open` branch zit.
- Benodigde ACK:
  - `I_UNDERSTAND_AND_APPROVE_D3_LIVE_EXIT_RECONCILIATION_APPLY`
- Voor apply eerst controleren:
  - orderstatus en snapshotbewijs
  - `filled_base`
  - `filled_quote`
  - `avg_fill_price`
  - `remaining_size`
  - `fees` indien beschikbaar
  - `position_size_base`
  - `bot_managed_base`
  - `reserved_base_open_exit_orders`
  - duplicate-exit guards
  - linked `position_id`
- Na apply direct sanitychecks:
  - local orderstatus coherent
  - reservation release of partial reservation coherent
  - geen negatieve base
  - D.2/D.3 alleen opnieuw preview-only

## Fase 3 — D.2/D.3 vervolg na TP1 lifecycle

- D.2 position status opnieuw read-only controleren.
- TP2/runner alleen preview-only.
- Nieuwe D.3 preview alleen na coherente base/reservation state.
- Nieuwe fingerprint review pas nadat de vorige lifecycle coherent is afgerond.
- Geen nieuwe SELL zonder aparte expliciete approval.

## Fase 4 — Controlled cancel-only governance

- Alleen relevant als governance expliciet een cancel-candidate wordt of cancel-first nodig is.
- Eerst cancel-only preflight.
- Daarna aparte cancel ACK:
  - `I_UNDERSTAND_AND_APPROVE_D3_OPEN_EXIT_CANCEL_GOVERNANCE`
- Geen replace in dezelfde stap.
- Na Coinbase `CANCELLED`:
  - closeout/release reservation dry-run
  - closeout apply pas met aparte reconciliation ACK
- Daarna pas nieuwe D.3 preview.

## Fase 5 — D.4 cancel/replace/trailing design

- Pas starten na afronding van de huidige open lifecycle.
- Gewenste onderdelen:
  - trailing activation
  - cancel/replace thresholds
  - stale-order logic
  - no atomic cancel+replace
  - reservation-aware replacement
  - duplicate-exit guard
  - min-size/min-quote/product-rules gating
- Eerst design en read-only tests.
- Daarna pas eventueel een controlled pilot.

## Fase 6 — D.5 execution learning

- Pas na complete exit lifecycle events.
- Inputs:
  - fill latency
  - maker/taker result
  - slippage
  - stale-open duration
  - cancel/replace decision quality
  - realized net edge
- Learning mag niet zonder aparte gate ingrijpen in live execution.

## Fase 7 — Documentatie en contextonderhoud

- `docs/CODEX_PROJECT_CONTEXT.md` blijft source of truth.
- `docs/D3_OPEN_EXIT_OPERATOR_RUNBOOK.md` blijft operator-handleiding voor de actuele open D.3 lifecycle.
- Monitorcheckpoints mogen later opgeschoond of gecomprimeerd worden.
- Cleanup pas als de open lifecycle stabiel of afgerond is.
- Geen documentatiecleanup die operationele context wist.

## Bundeling: wat wel en niet samen mag

### Bundelbaar

- read-only snapshot + reconcile dry-run + governance previews
- na statuswijziging: dry-run analyse + docs checkpoint
- na closeout/fill apply: D.2 status + D.3 preview-only
- documentatiecheckpoint + operatoradvies

### Niet bundelen

- cancel en replace
- apply en nieuwe SELL
- closeout apply en nieuwe preview-submit
- recovery apply en live action
- service restart en trading lifecycle
- ACK-gebruik met andere acties

## Compacte beslisboom

- If `OPEN/open` -> `keep_open`, stop
- If `PARTIAL` -> dry-run, stop for ACK
- If `FILLED` -> dry-run, stop for ACK
- If `CANCELLED/EXPIRED/REJECTED` -> dry-run, stop for ACK
- If `cancel_candidate` -> controlled cancel-only plan, stop
- If `replace_candidate` -> cancel-first sequence, stop
- If inconsistent local state -> diagnose-only, no recovery apply without approval

## Prioriteitenlijst

| prioriteit | fase | actie | type | mag gebundeld worden met | stopconditie | risico |
| --- | --- | --- | --- | --- | --- | --- |
| P0 | Fase 1 | Current open TP1 lifecycle read-only bewaken | read-only | snapshot + reconcile + governance previews | branch blijft `OPEN/open keep_open` | onnodige live actie tijdens open lifecycle |
| P1 | Fase 1 | PARTIAL branch analyseren | ACK-required | snapshot + reconcile dry-run + docs checkpoint | dry-run compleet, wacht op ACK | foutieve partial apply / reservation drift |
| P1 | Fase 1 | FILLED branch analyseren | ACK-required | snapshot + reconcile dry-run + docs checkpoint | dry-run compleet, wacht op ACK | foutieve finalization / verkeerde base-reductie |
| P1 | Fase 1 | CANCELLED/EXPIRED/REJECTED branch analyseren | ACK-required | snapshot + reconcile dry-run + docs checkpoint | dry-run compleet, wacht op ACK | incoherent closeout / reservation leak |
| P1 | Fase 4 | Controlled cancel-only governance | ACK-required | cancel preflight + later poll plan | wacht op aparte cancel-sessie | premature cancel of implicit replace |
| P2 | Fase 3 | D.2 status en D.3 vervolg preview-only | read-only | na apply of coherente closeout | nieuwe preview/fingerprint beoordeeld | te vroeg nieuwe SELL voorbereiden |
| P3 | Fase 5 | D.4 cancel/replace/trailing design | later design | design docs + tests | design klaar, geen live pilot | design tijdens actieve lifecycle verstoort focus |
| P4 | Fase 6 | D.5 execution learning | later design | postmortem + metrics review | genoeg lifecycle events verzameld | learning beïnvloedt execution zonder gate |
| P5 | Fase 7 | Documentatiecleanup/compressie | forbidden now | later samen met afgeronde lifecycle | lifecycle stabiel of afgerond | verlies van operationele context |
