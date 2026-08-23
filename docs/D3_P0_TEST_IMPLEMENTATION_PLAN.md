# D.3 P0 test implementation plan

## 1. Purpose

Dit plan zet alleen de P0-testset om naar een veilige implementatievolgorde op basis van de huidige D.3-reconcilelogica, bestaande testhelpers en de actuele `OPEN/open keep_open` freeze. Het document geeft aan waar elke test het best landt, welke fixtures al bestaan, welke assertions nog ontbreken en wanneer implementatie moet stoppen voordat productielogica of livegedrag geraakt wordt.

## 2. Rules for implementation

- Tests moeten pure local fixtures gebruiken.
- Geen Coinbase client gebruiken.
- Geen live state gebruiken.
- Geen `.env`-afhankelijkheid introduceren.
- Geen serviceprocessen gebruiken.
- Geen live submit/cancel/replace/apply uitvoeren.
- State mutation alleen binnen `tmp_path` en testfixtures.

## 3. Existing helpers and fixtures

- `tests/test_phase_d3_live_exit_reconciliation.py` is de primaire uitbreidingslocatie voor alle vijf P0-tests.
- `_seed_position(store)` maakt een standaard open `BTC-USDC`-positie met `position_size_base=0.10` en `bot_managed_base=0.10`.
- `_seed_live_exit(store, status="submitted")` maakt de standaard open D.3 TP1 SELL met `size_base=0.04` en `remaining_size=0.04`.
- `_snapshot(normalized_status, ...)` bouwt lokale Coinbase-snapshotfixtures voor `open`, `partially_filled`, `filled`, `cancelled`, `expired` en `rejected`.
- `_run(tmp_path, monkeypatch, snapshot=..., apply=False, apply_ack="")` zet `OrderStore` en `StateStore` lokaal op en voert één reconcile-call uit.
- Bestaande assertions in hetzelfde bestand dekken al:
  - `OPEN/open keep_open`
  - apply-block op `OPEN/open`
  - rejected/cancelled/expired dry-run
  - partial/fill dry-run
  - partial apply en idempotentie
  - duplicate-order blocks
  - oversize/managed-base blocks
  - unknown snapshot blocking
  - available-only managed-base semantiek bij partial/filled
- `tests/test_phase_d3_reservation_governance.py` bevat bruikbare referentie-assertions voor:
  - `reserved_base_open_exit_orders`
  - `available_base_after_reservations`
  - `available_plus_reserved_base`
  - `available_reserved_matches_bot_manageable_base`
- `tests/test_phase_d3_controlled_live_exits.py` bevat bruikbare referentie-assertions voor no-oversell, duplicate exit labels/actions en reservation governance in rapportage.
- `tests/test_coinbase_order_snapshot.py` is relevant als snapshotnormalisatie later extra dekking nodig heeft, maar niet de eerste uitbreidingslocatie voor deze P0-set.
- Productiemodules die de P0-tests direct exercisen:
  - `bot/phase_d3_live_exit_reconciliation.py`
  - `bot/order_store.py`
- Productiemodules die alleen indirecte semantische referentie geven:
  - `bot/phase_d3_reservation_governance.py`
  - `bot/phase_d3_controlled_live_exits.py`

## 4. P0 test plan

### test_d3_open_keep_open_preserves_order_counts_and_position_snapshot

- Doel: bewijzen dat `OPEN/open keep_open` niet alleen `keep_open` rapporteert, maar ook lokale ordertellingen en positionsnapshot exact ongemoeid laat.
- Bestaand testbestand om uit te breiden: `tests/test_phase_d3_live_exit_reconciliation.py`
- Benodigde fixtures:
  - `_seed_position`
  - `_seed_live_exit`
  - `_snapshot("open")`
  - lokale `OrderStore` en `StateStore`
- Bestaande helpers die hergebruikt kunnen worden:
  - `_run(...)`
  - `order_store.open_order_counts()`
  - `state_store.get_position("BTC-USDC")`
- Nieuwe assertions:
  - open-order counts vóór en na reconcile zijn exact gelijk
  - lokaal orderrecord vóór en na reconcile is exact gelijk
  - positionsnapshot vóór en na reconcile is exact gelijk
  - `report["no_state_write"] is True`
  - `report["proposed_order_updates"] == {}`
  - `report["proposed_position_updates"] == {}`
- Mogelijke productiemodule die later geraakt kan worden: `bot/phase_d3_live_exit_reconciliation.py`
- Expected result: dry-run `OPEN/open` blijft volledig mutation-free en houdt zowel orderstore als positionstore bitwise/coherent gelijk op functioneel niveau.
- Live-safety note: pure `tmp_path`-store, geen live client, geen apply-pad.
- Implementatierisico: laag; helpers bestaan al en deze test verbreedt alleen bestaande `keep_open`-dekking.
- Volgorde binnen P0: 1

### test_d3_unknown_network_failure_never_proposes_apply_or_trading_action

- Doel: expliciet vastleggen dat network/snapshot failure fail-closed blijft en geen voorstel tot apply of nieuwe tradingactie oplevert.
- Bestaand testbestand om uit te breiden: `tests/test_phase_d3_live_exit_reconciliation.py`
- Benodigde fixtures:
  - `_seed_position`
  - `_seed_live_exit`
  - lokale failure-snapshot met `coinbase_call_succeeded=False` en `normalized_status="unknown"`
- Bestaande helpers die hergebruikt kunnen worden:
  - `_run(...)`
- Nieuwe assertions:
  - `report["status"] == "d3_live_exit_reconcile_blocked"`
  - `report["suggested_action"] == "unknown_no_apply"`
  - `coinbase_snapshot_unavailable` in blockers
  - `coinbase_snapshot_status_unknown_or_unsupported` in blockers
  - `report["proposed_order_updates"] == {}`
  - `report["proposed_position_updates"] == {}`
  - `report["no_state_write"] is True`
  - geen `*_ready` of `*_applied` status
- Mogelijke productiemodule die later geraakt kan worden: `bot/phase_d3_live_exit_reconciliation.py`
- Expected result: unknown/network failure blijft hard blocked, dry-run only en kan niet doorschuiven naar reconcile-apply of een andere trading branch.
- Live-safety note: gebruikt alleen synthetische snapshotdata; geen Coinbase client of retries.
- Implementatierisico: laag; bestaande `test_unknown_snapshot_blocks` kan rechtstreeks verdiept worden.
- Volgorde binnen P0: 2

### test_d3_filled_apply_revalidates_available_reserved_managed_base_semantics

- Doel: bevestigen dat de FILLED-apply branch de huidige available/reserved/managed-base semantiek coherent afrondt, inclusief reservation release en position closeout-logica wanneer van toepassing.
- Bestaand testbestand om uit te breiden: `tests/test_phase_d3_live_exit_reconciliation.py`
- Benodigde fixtures:
  - maatwerkpositie met `position_size_base=0.06` en `bot_managed_base=0.10`
  - `_seed_live_exit`
  - `_snapshot("filled", filled_base="0.04", filled_quote="3266.5988", avg_fill_price="81664.97", fill_count=1)`
  - lokale `OrderStore` en `StateStore`
- Bestaande helpers die hergebruikt kunnen worden:
  - `_seed_live_exit`
  - pattern uit `test_full_fill_allowed_when_position_base_is_available_only`
  - pattern uit `test_apply_partial_fill_updates_order_and_position`
  - referentie-assertions uit `tests/test_phase_d3_reservation_governance.py`
- Nieuwe assertions:
  - apply-status wordt `d3_live_exit_reconcile_filled_applied`
  - applied/local order krijgt `status="filled"` en `remaining_size="0"`
  - position na apply houdt `position_size_base == bot_managed_base == "0.06"`
  - `last_d3_reconcile_reserved_base_this_exit_after_fill == "0"`
  - `last_d3_reconcile_total_managed_base_before_fill == "0.10"`
  - geen negatieve base en geen verborgen reservationrestant
  - wanneer positie niet flat is: status blijft coherent open in plaats van impliciet gesloten
- Mogelijke productiemodule die later geraakt kan worden: `bot/phase_d3_live_exit_reconciliation.py`
- Expected result: FILLED-apply valideert open-hold semantiek en released de TP1-reservation zonder bot-managed-base incoherentie.
- Live-safety note: alleen lokale stores en ACK-string in testfixture; geen echte apply buiten `tmp_path`.
- Implementatierisico: middel; combineert bestaande filled dry-run semantiek met nieuw apply-assertieoppervlak.
- Volgorde binnen P0: 3

### test_d3_cancelled_closeout_requires_coherent_post_closeout_preview_state

- Doel: afdwingen dat een CANCELLED-closeout pas als coherent telt wanneer de lokale order finaliseert, de reservation verdwijnt en de resterende positie daarna previewbaar blijft zonder open D.3 collision.
- Bestaand testbestand om uit te breiden: `tests/test_phase_d3_live_exit_reconciliation.py`
- Benodigde fixtures:
  - `_seed_position`
  - `_seed_live_exit`
  - `_snapshot("cancelled")`
  - lokale `OrderStore` en `StateStore`
- Bestaande helpers die hergebruikt kunnen worden:
  - `_run(...)`
  - pattern uit `test_cancelled_snapshot_dry_run_proposes_cancelled`
  - `order_store.open_exit_orders("BTC-USDC")`
  - `order_store.final_orders("BTC-USDC")`
  - eventueel `build_phase_d3_reservation_governance_snapshot(...)` als vervolgreferentie voor reservationvrij resultaat
- Nieuwe assertions:
  - dry-run status is `d3_live_exit_reconcile_cancelled_ready`
  - apply-status wordt `d3_live_exit_reconcile_cancelled_applied`
  - lokale order krijgt `status="cancelled"`, `remaining_size="0"`, `closed_at`/`finalized_at`
  - `order_store.open_exit_orders("BTC-USDC") == []`
  - positiebase en bot-managed-base blijven gelijk aan pre-closeout waarden
  - post-closeout reservation snapshot toont `reserved_base_open_exit_orders == "0"`
- Mogelijke productiemodule die later geraakt kan worden: `bot/phase_d3_live_exit_reconciliation.py`
- Expected result: cancel-closeout finaliseert de order lokaal zonder base-verlies en laat een schone preview-state achter voor latere governance.
- Live-safety note: alleen lokale closeout-simulatie; geen cancel-call, geen replace-call.
- Implementatierisico: middel; kan aanvullende helpercode binnen de test vereisen om post-closeout governance-snapshot expliciet te maken.
- Volgorde binnen P0: 4

### test_d3_partial_fill_multiple_deltas_preserve_remaining_reservation

- Doel: bewijzen dat opeenvolgende partial-fill deltas idempotent en reservation-coherent blijven, met correcte afbouw van `remaining_size` zonder dubbele base-reductie.
- Bestaand testbestand om uit te breiden: `tests/test_phase_d3_live_exit_reconciliation.py`
- Benodigde fixtures:
  - `_seed_position`
  - `_seed_live_exit`
  - twee oplopende partial snapshots, bijvoorbeeld eerst `filled_base="0.01"` en daarna `filled_base="0.025"`
  - lokale `OrderStore` en `StateStore`
- Bestaande helpers die hergebruikt kunnen worden:
  - pattern uit `test_apply_partial_fill_updates_order_and_position`
  - pattern uit `test_apply_is_idempotent_for_already_applied_partial`
  - pattern uit `test_partial_fill_allowed_when_position_base_is_available_only`
- Nieuwe assertions:
  - eerste apply reduceert alleen delta `0.01`
  - tweede apply reduceert alleen extra delta `0.015`
  - `remaining_size` loopt van `0.04` naar `0.03` naar `0.015`
  - `last_d3_reconcile_reserved_base_this_exit_after_fill` volgt de resterende reservation exact
  - `bot_managed_base` en `position_size_base` blijven coherent na beide applies
  - herhaalde tweede snapshot blijft idempotent en veroorzaakt geen extra base-verlies
- Mogelijke productiemodule die later geraakt kan worden: `bot/phase_d3_live_exit_reconciliation.py`
- Expected result: multi-delta partials behouden de resterende open-reservation en voorkomen dubbele verwerking van eerder toegepaste fills.
- Live-safety note: uitsluitend lokale apply tegen tmp fixtures; geen live order lifecycle.
- Implementatierisico: hoogst binnen P0; dit is de meest stateful variant en moet pas na de eerdere P0-tests worden opgepakt.
- Volgorde binnen P0: 5

## 5. Recommended implementation order

1. `test_d3_open_keep_open_preserves_order_counts_and_position_snapshot`
2. `test_d3_unknown_network_failure_never_proposes_apply_or_trading_action`
3. `test_d3_filled_apply_revalidates_available_reserved_managed_base_semantics`
4. `test_d3_cancelled_closeout_requires_coherent_post_closeout_preview_state`
5. `test_d3_partial_fill_multiple_deltas_preserve_remaining_reservation`

Deze volgorde blijft de veiligste omdat hij begint met read-only/no-mutation invariants, daarna fail-closed gedrag vastlegt, vervolgens één coherent FILLED-apply pad uitdiept, daarna closeout zonder nieuwe order branch behandelt en pas als laatste de meest stateful multi-delta partial-case toevoegt.

## 6. Stop conditions

- Stop zodra testimplementatie productielogica vereist in plaats van alleen assertions op bestaand gedrag.
- Stop zodra een fixture onzeker is over de bedoelde D.3 open-hold semantiek.
- Stop zodra een live client nodig lijkt.
- Stop zodra bestaande helpers onduidelijk blijken voor order/position baselinevergelijking.
- Stop zodra een test alleen haalbaar lijkt na wijziging van `bot/phase_d3_live_exit_reconciliation.py`, `bot/order_store.py` of andere productiemodules.
- Dan eerst rapporteren en niet patchen.

## 7. Next Codex prompt after this plan

Gebruik deze veilige vervolgronde:

```text
We gaan verder met het Coinbase spot LLM tradingbot-project.

Werkdirectory:
/root/apps/Crypto/coinbase_bot

Lees eerst volledig:
- docs/CODEX_PROJECT_CONTEXT.md
- docs/D3_P0_TEST_IMPLEMENTATION_PLAN.md
- docs/D3_D4_TEST_COVERAGE_MAPPING.md
- docs/D3_D4_TEST_AND_SAFETY_MATRIX.md
- docs/D3_OPEN_EXIT_OPERATOR_RUNBOOK.md

Deze ronde is alleen implementatie van de eerste P0-test:
- test_d3_open_keep_open_preserves_order_counts_and_position_snapshot

Niet uitvoeren:
- geen live statuscheck
- geen Coinbase call
- geen live BUY/SELL
- geen apply buiten lokale testfixture
- geen tests draaien die live clients raken

Doel:
- breid alleen tests/test_phase_d3_live_exit_reconciliation.py uit
- gebruik alleen bestaande lokale fixtures/helpers
- implementeer alleen deze ene test
- voer daarna alleen de minimale lokale pytest-selectie uit als die geen Coinbase/live client raakt
- rapporteer blockers direct en patch niets anders
```
