# Next step approval plan

## 1. Huidige voortgang

Klaar:

- architectuur-, roadmap-, execution- en safetydocumentatie staat
- actuele D.3 operator-runbook staat
- volledige P0-testset is groen
- laatste lokale D.3 reconcile testselectie: `23 passed, 1 warning`
- geen `bot/`- of `tools/`-productielogica aangepast voor P0

Groen getest:

- `test_d3_open_keep_open_preserves_order_counts_and_position_snapshot`
- `test_d3_unknown_network_failure_never_proposes_apply_or_trading_action`
- `test_d3_filled_apply_revalidates_available_reserved_managed_base_semantics`
- `test_d3_cancelled_closeout_requires_coherent_post_closeout_preview_state`
- `test_d3_partial_fill_multiple_deltas_preserve_remaining_reservation`

Nog open:

- exact één D.3 TP1 live SELL voor `BTC-USDC`
- laatste bekende branch: `OPEN/open keep_open`

Wat absoluut nog niet mag:

- live BUY
- live SELL
- tweede SELL
- retry
- cancel
- replace
- reconcile apply
- recovery apply
- `.env`-mutatie
- service restart
- state mutation
- ACK-gebruik

## 2. Fase A — P1 test readiness afronden

Aanbevolen volgorde:

1. `test_d3_rejected_branch_preserves_no_new_sell_before_closeout_complete`
2. `test_d3_cancel_replace_governance_blocks_replace_until_cancelled_closeout_applied`
3. `test_d3_cancel_replace_governance_blocks_when_replication_enabled`

Waarom:

- de REJECTED-branch sluit direct aan op bestaande D.3 reconcile-dekking en houdt de focus eerst op lifecycle-closeout, niet op D.4-governance
- daarna is cancel-first sequencing de belangrijkste safety-voorwaarde vóór latere cancel/replace-branches
- replication isolation is belangrijk, maar logisch als derde omdat die op governance-blocking leunt en geen hoofdbranch van de huidige open order is

### Test 1

- doel: bewijzen dat een rejected lifecycle geen nieuwe SELL- of preview-submit readiness creëert vóór coherente closeout
- waarom nodig: REJECTED is een P1-reconcilebranch en moet fail-closed blijven
- exacte actie: planning -> implementatie van één test in [tests/test_phase_d3_live_exit_reconciliation.py](/root/apps/Crypto/coinbase_bot/tests/test_phase_d3_live_exit_reconciliation.py), mogelijk met referentie uit [tests/test_phase_d3_rejected_submit_cleanup.py](/root/apps/Crypto/coinbase_bot/tests/test_phase_d3_rejected_submit_cleanup.py)
- type: `test-only`
- waarschijnlijke bestanden: `tests/test_phase_d3_live_exit_reconciliation.py`
- tests die gedraaid mogen worden: `PYTHONPATH=. .venv/bin/pytest -q tests/test_phase_d3_live_exit_reconciliation.py`
- stopconditie: als reject-semantiek alleen te testen blijkt via aanpassing van `bot/phase_d3_live_exit_reconciliation.py`
- menselijke goedkeuring nodig: ja, vóór implementatie
- wat pas daarna mag: volgende P1-test of bredere regressie

### Test 2

- doel: bewijzen dat replace geblokkeerd blijft totdat cancelled-closeout coherent is toegepast
- waarom nodig: cancel-first is de kerninvariant vóór elke latere D.4 replace-branch
- exacte actie: planning -> implementatie van één governance-test in [tests/test_phase_d3_cancel_replace_governance.py](/root/apps/Crypto/coinbase_bot/tests/test_phase_d3_cancel_replace_governance.py)
- type: `test-only`
- waarschijnlijke bestanden: `tests/test_phase_d3_cancel_replace_governance.py`
- tests die gedraaid mogen worden: `PYTHONPATH=. .venv/bin/pytest -q tests/test_phase_d3_cancel_replace_governance.py`
- stopconditie: als bestaande governance-reporting onvoldoende is zonder `tools/show_phase_d3_cancel_replace_governance.py` of productielogica te wijzigen
- menselijke goedkeuring nodig: ja
- wat pas daarna mag: derde P1-test of brede regressie

### Test 3

- doel: bewijzen dat replication/follower enabled cancel-only governance blokkeert
- waarom nodig: follower-isolatie moet expliciet groen zijn vóór cancel-only of latere D.4-paden
- exacte actie: planning -> implementatie van één governance-test in [tests/test_phase_d3_cancel_replace_governance.py](/root/apps/Crypto/coinbase_bot/tests/test_phase_d3_cancel_replace_governance.py)
- type: `test-only`
- waarschijnlijke bestanden: `tests/test_phase_d3_cancel_replace_governance.py`
- tests die gedraaid mogen worden: `PYTHONPATH=. .venv/bin/pytest -q tests/test_phase_d3_cancel_replace_governance.py`
- stopconditie: als replication-blocking alleen via runtime/productielogica aanpassing aantoonbaar wordt
- menselijke goedkeuring nodig: ja
- wat pas daarna mag: brede regressie

Eerste P1-test na goedkeuring:

- `test_d3_rejected_branch_preserves_no_new_sell_before_closeout_complete`

## 3. Fase B — Brede lokale regressie na P0/P1

- doel: bewijzen dat P0/P1-testuitbreidingen geen bestaande D.2/D.3/C.4.3/C.4.5 safety breken
- waarom nodig: lokale branchdekking is niet genoeg; gates en governance moeten samen groen blijven
- exacte actie: alleen na P1-implementatie een bredere lokale pytest-selectie draaien
- type: `test-only`
- waarschijnlijke bestanden: alleen bestaande tests
- logische testselectie:
  - [tests/test_phase_d3_live_exit_reconciliation.py](/root/apps/Crypto/coinbase_bot/tests/test_phase_d3_live_exit_reconciliation.py)
  - [tests/test_phase_d3_controlled_live_exits.py](/root/apps/Crypto/coinbase_bot/tests/test_phase_d3_controlled_live_exits.py)
  - [tests/test_phase_d3_cancel_replace_governance.py](/root/apps/Crypto/coinbase_bot/tests/test_phase_d3_cancel_replace_governance.py)
  - [tests/test_phase_d3_open_exit_order_governance.py](/root/apps/Crypto/coinbase_bot/tests/test_phase_d3_open_exit_order_governance.py)
  - [tests/test_phase_d3_reservation_governance.py](/root/apps/Crypto/coinbase_bot/tests/test_phase_d3_reservation_governance.py)
  - [tests/test_phase_d3_rejected_submit_cleanup.py](/root/apps/Crypto/coinbase_bot/tests/test_phase_d3_rejected_submit_cleanup.py)
  - [tests/test_live_exit_gate.py](/root/apps/Crypto/coinbase_bot/tests/test_live_exit_gate.py)
  - [tests/test_coinbase_executor_live_exit_gate.py](/root/apps/Crypto/coinbase_bot/tests/test_coinbase_executor_live_exit_gate.py)
  - [tests/test_strategy_engine_live_exit_gate.py](/root/apps/Crypto/coinbase_bot/tests/test_strategy_engine_live_exit_gate.py)
  - [tests/test_function_preservation_audit.py](/root/apps/Crypto/coinbase_bot/tests/test_function_preservation_audit.py)
  - [tests/test_phase_d2_position_executor.py](/root/apps/Crypto/coinbase_bot/tests/test_phase_d2_position_executor.py)
  - [tests/test_coinbase_order_snapshot.py](/root/apps/Crypto/coinbase_bot/tests/test_coinbase_order_snapshot.py)
- stopconditie: eerste regressiefout stopt de sessie; geen verbreding naar meer tests
- menselijke goedkeuring nodig: ja
- wat pas daarna mag: read-only operationele D.3 statuscheck

## 4. Fase C — Read-only operationele D.3 statuscheck

- doel: pas na test/readiness-werk de echte open TP1 lifecycle opnieuw beoordelen
- waarom nodig: operationele branch kan veranderd zijn; planning mag niet op oude status blijven steunen
- exacte actie: uitsluitend read-only audit en statuscommando’s
- type: `read-only statuscheck`
- waarschijnlijke bestanden: geen codewijziging; alleen read-only tools
- tests/commands:

```bash
PYTHONPATH=. .venv/bin/python tools/show_function_preservation_audit.py --fail-on-review

PYTHONPATH=. .venv/bin/python tools/show_phase_c43_autonomous_entry_live.py \
  --ticker BTC-USDC \
  --order-store state/open_orders.json \
  --json

PYTHONPATH=. .venv/bin/python tools/show_phase_d3_live_exit_order_snapshot.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --json

PYTHONPATH=. .venv/bin/python tools/reconcile_phase_d3_live_exit_order.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --dry-run \
  --json

PYTHONPATH=. .venv/bin/python tools/show_phase_d3_open_exit_order_governance.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --json

PYTHONPATH=. .venv/bin/python tools/show_phase_d3_cancel_replace_governance.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --json
```

- stopconditie: bij onbekende/inconsistente output geen follow-up actie behalve diagnose-only planning
- menselijke goedkeuring nodig: ja, vóór uitvoering
- wat pas daarna mag: branchafhandeling uit Fase D

## 5. Fase D — Branchafhandeling na statuscheck

- doel: de operationele branch exact scheiden vóór enige ACK-sessie
- waarom nodig: elke status heeft andere safety-eisen
- exacte actie: beslisboom toepassen op de read-only outputs
- type: `planning-only`
- waarschijnlijke bestanden: docs/checkpoints
- beslisboom:
  - `OPEN/open` -> `keep_open`, stop
  - `PARTIAL` -> reconcile dry-run beoordelen, stop voor ACK
  - `FILLED` -> reconcile dry-run beoordelen, stop voor ACK
  - `CANCELLED/EXPIRED/REJECTED` -> reconcile dry-run beoordelen, stop voor ACK
  - `cancel_candidate` -> controlled cancel-only plan opstellen, stop voor ACK
  - `replace_candidate` -> cancel-first sequence opstellen, stop voor ACK
  - inconsistent state -> diagnose-only, geen recovery apply
- stopconditie: nooit doorlopen naar apply/cancel/replace in dezelfde sessie zonder expliciete aparte goedkeuring
- menselijke goedkeuring nodig: pas bij overgang naar Fase E of cancel-only voorbereiding
- wat pas daarna mag: ACK-required voorbereiding

## 6. Fase E — ACK-required reconcile apply

- doel: alleen bij echte statuswijziging een lokale reconcile-apply veilig voorbereiden
- waarom nodig: apply is state mutation en dus aparte operatorbeslissing
- exacte actie: eerst pre-apply snapshotset, dan command-template klaarzetten, niet uitvoeren zonder ACK
- type: `ACK-required`
- waarschijnlijke bestanden: `state/open_orders.json`, `state/positions.json`, logs, docs checkpoints
- pre-apply snapshot checklist:
  - `state/open_orders.json`
  - `state/positions.json`
  - `logs/order_events.jsonl`
  - `logs/live_exit_orders.jsonl`
  - `logs/phase_d2_position_executor.jsonl`
  - actuele D.3 snapshot output
  - reconcile dry-run output
  - actuele D.2 report
  - actuele D.3 report
  - audit output
  - `client_order_id`, `exchange_order_id`, `linked_position_id`
- benodigde ACK:
  - `I_UNDERSTAND_AND_APPROVE_D3_LIVE_EXIT_RECONCILIATION_APPLY`
- minimale apply command template, niet uitvoeren:

```bash
PYTHONPATH=. .venv/bin/python tools/reconcile_phase_d3_live_exit_order.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --apply \
  --apply-ack I_UNDERSTAND_AND_APPROVE_D3_LIVE_EXIT_RECONCILIATION_APPLY \
  --json
```

- post-apply sanity checklist:
  - audit ok
  - order status coherent
  - `position_size_base` coherent
  - `bot_managed_base` coherent
  - `reserved_base` coherent
  - no duplicate exits
  - no negative base
  - open order counts coherent
  - D.2/D.3 daarna alleen preview-only
  - docs checkpoint updated
- stopconditie: elke incoherentie of onverwachte base/reservation drift stopt de sessie
- menselijke goedkeuring nodig: ja, expliciet
- wat pas daarna mag: Fase F

## 7. Fase F — D.2/D.3 vervolg na coherente apply

- doel: pas na coherente apply of closeout de positie- en exitplanning opnieuw bekijken
- waarom nodig: D.2 fingerprint en D.3 preview mogen pas op actuele lokale state draaien
- exacte actie: alleen read-only D.2 status en D.3 preview/fingerprint
- type: `read-only statuscheck`
- waarschijnlijke bestanden: geen codewijziging; bestaande tools/reports
- read-only command templates:

```bash
PYTHONPATH=. .venv/bin/python tools/show_phase_d2_position_executor.py --ticker BTC-USDC --json

PYTHONPATH=. .venv/bin/python tools/show_phase_d3_controlled_exit_pilot.py \
  --ticker BTC-USDC \
  --preview-only \
  --json
```

- invarianten die groen moeten zijn:
  - order lifecycle coherent gesloten of coherent partial
  - `position_size_base` en `bot_managed_base` kloppen
  - geen reserved-base leak
  - geen duplicate exits
  - fingerprint coherent met actuele positie
  - preview-only status zonder submit
- wanneer een volgende SELL besproken mag worden:
  - pas na coherente apply
  - pas na nieuwe D.3 preview/fingerprint review
  - pas met aparte expliciete menselijke approval
- stopconditie: fingerprint mismatch, reservation drift of nieuwe blockers
- menselijke goedkeuring nodig: ja, als een nieuwe SELL-branch besproken zou worden
- wat pas daarna mag: D.4-design of later nieuwe one-shot SELL-approval

## 8. Fase G — D.4 ontwerp pas daarna

- doel: cancel/replace/trailing pas na afronding van de huidige lifecycle ontwerpen
- waarom nodig: D.4 mag niet concurreren met een open D.3 lifecycle
- exacte actie: design- en testplanning, geen live pilot
- type: `planning-only`
- waarschijnlijke bestanden:
  - `tests/test_phase_d3_cancel_replace_governance.py`
  - `tests/test_phase_d3_open_exit_order_governance.py`
  - `tests/test_phase_d3_reservation_governance.py`
  - `docs/D3_D4_TEST_AND_SAFETY_MATRIX.md`
  - nieuwe D.4 design docs indien nodig
- concrete D.4 items:
  - stale thresholds exact maken
  - cancel-candidate criteria exact maken
  - replace-candidate criteria exact maken
  - cancel-first sequence uitwerken
  - no atomic cancel+replace blijven afdwingen
  - reservation-aware replacement uitwerken
  - product-rules gating voor replacement/trailing uitwerken
  - logging/observability eventlijst uitwerken
  - controlled pilot criteria formuleren
- wat verboden blijft:
  - live cancel
  - live replace
  - trailing live pilot
  - atomic cancel+replace
- wanneer D.4 pilot denkbaar wordt:
  - huidige D.3 lifecycle coherent afgerond
  - P1/P2 tests groen
  - regressie groen
  - read-only governance kandidaat helder
  - aparte operatorgoedkeuring

## 9. Fase H — D.5 execution learning

- doel: learning pas na complete exit lifecycle-events
- waarom nodig: execution learning zonder volledige lifecycle-data is misleidend en onveilig
- exacte actie: alleen analyse- en datamodelplanning
- type: `planning-only`
- waarschijnlijke bestanden: toekomstige D.5 docs/tests, mogelijk audit/reporting docs
- data die nodig is:
  - fill latency
  - maker/taker result
  - slippage
  - stale-open duration
  - cancel/replace decision quality
  - realized net edge
  - partial/final lifecycle markers
- welke learning analyse-only blijft:
  - postmortem metrics
  - clustering van goede/slechte exits
  - thresholds evalueren
  - recommendation scoring
- gate die nodig is vóór learning execution mag beïnvloeden:
  - aparte execution gate die losstaat van analyse
  - geen automatische mutatie van live thresholds of submitgedrag zonder expliciete menselijke approval

## 10. Prioriteitentabel

| prioriteit | fase | stap | actie | type | bestanden | tests/commands | menselijke goedkeuring nodig? | stopconditie | verwacht resultaat |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P0 | A | A1 | eerste P1-test bouwen: rejected branch | test-only | `tests/test_phase_d3_live_exit_reconciliation.py` | `pytest -q tests/test_phase_d3_live_exit_reconciliation.py` | ja | productielogica nodig | REJECTED-branch beter afgedekt |
| P0 | A | A2 | tweede P1-test bouwen: cancel-first replace block | test-only | `tests/test_phase_d3_cancel_replace_governance.py` | `pytest -q tests/test_phase_d3_cancel_replace_governance.py` | ja | governance-helper ontoereikend | cancel-first expliciet groen |
| P1 | A | A3 | derde P1-test bouwen: replication block | test-only | `tests/test_phase_d3_cancel_replace_governance.py` | `pytest -q tests/test_phase_d3_cancel_replace_governance.py` | ja | runtime/productielogica vereist | follower-isolatie expliciet groen |
| P1 | B | B1 | brede regressie draaien | test-only | bestaande testbestanden | regressieset uit fase B | ja | eerste failure | gates en D.2/D.3 safety blijven groen |
| P1 | C | C1 | actuele D.3 TP1 read-only statuscheck | read-only statuscheck | geen | audit + C.4.3 + D.3 snapshot/reconcile/governance commands | ja | inconsistent output | actuele branch bevestigd |
| P1 | D | D1 | branch beslissen op basis van statuscheck | planning-only | docs/checkpoint | geen | nee | branch onduidelijk | juiste vervolgbranch gekozen |
| P2 | E | E1 | reconcile apply alleen voorbereiden | ACK-required | state/logs/docs | apply-template, niet uitvoeren zonder ACK | ja | snapshot of dry-run incoherent | veilige apply-ready sessie |
| P2 | F | F1 | D.2/D.3 vervolg preview-only | read-only statuscheck | read-only tools/docs | D.2 status + D.3 preview commands | ja, als nieuwe SELL besproken wordt | fingerprint/reservation mismatch | coherente vervolgplanning |
| P3 | G | G1 | D.4 design starten | planning-only | D.4 tests/docs | geen of read-only repo inspectie | ja | huidige lifecycle niet afgerond | D.4 ontwerp backlog helder |
| P4 | H | H1 | D.5 learning ontwerp starten | planning-only | toekomstige D.5 docs/tests | geen | ja | onvoldoende lifecycle-data | learning blijft analysis-only |

## 11. Goedkeuringspunten

Goedkeuring 1:

- P1-testimplementatie starten?
- eerste P1-test: `test_d3_rejected_branch_preserves_no_new_sell_before_closeout_complete`

Goedkeuring 2:

- brede lokale regressie draaien na P1?

Goedkeuring 3:

- read-only live statuscheck van de huidige D.3 TP1-order doen?

Goedkeuring 4:

- alleen indien statuswijziging: reconcile-apply voorbereiden?

Goedkeuring 5:

- alleen indien governance candidate: cancel-only sessie voorbereiden?

Goedkeuring 6:

- D.4 design starten na huidige lifecycle?
