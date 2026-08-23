# D.3 local position reconstruction preview

## 1. Purpose

Dit document is preview-only.

Er wordt geen state gemuteerd, geen recovery apply uitgevoerd en geen live actie voorgesteld.

Doel is de local/live mismatch rond de open D.3 TP1 `SELL` voor `BTC-USDC` expliciet te maken voordat herstel later eventueel wordt overwogen.

## 2. Current mismatch

- Live D.3 order op Coinbase: `OPEN/open`
- Lokale D.3 order in `state/open_orders.json`: `submitted/open`
- Lokale `BTC-USDC` positie in `state/positions.json`: `closed`, `position_size_base=0`, `bot_managed_base=0`
- Actieve governance blocker: `local_position_not_open`

De bot ziet dus tegelijk een echte open D.3 exit-order en een lokaal gesloten positie. Daardoor blokkeren D.2, D.3 en cancel/replace governance terecht fail-closed.

## 3. Evidence timeline

- `2026-05-26T09:49:38Z`
  - D.3 TP1 `SELL` live ingediend
  - `client_order_id=phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000`
  - `exchange_order_id=bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31`
  - `linked_position_id=76310097-849e-481c-b587-ba44bc3330fe`
  - submit-evidence toont `position_base=0.0001297967431275` en `sell_base=0.00006489`
- `2026-05-26T10:56:37Z`
  - lokale positie werd eerder al eens hersteld vanuit tiny-residual-close
  - `recovery_reason=live_base_present_after_inventory_sync_tiny_residual_close`
- `2026-05-26T15:00:04Z` tot `2026-05-26T15:00:05Z`
  - logs tonen dat de positie nog expliciet open werd gehouden
  - `status=open`
  - `position_size_base=0.0000649067431275`
  - `bot_managed_base=0.0001297967431275`
  - `last_heartbeat_reason=inventory_sync_position_kept_open_due_to_open_d3_exit_order`
- `2026-05-26T16:00:00.517331Z`
  - lokale positie werd opnieuw gesloten naar tiny residual
  - `status=closed`
  - `position_size_base=0`
  - `bot_managed_base=0`
  - `close_reason=inventory_sync_live_notional_below_min_trade_quote`
  - `last_heartbeat_status=closed_tiny_residual`
- Laatste read-only Fase C/Fase D diagnose
  - live order nog `OPEN/open`
  - `filled_base=0`
  - `filled_quote=0`
  - `fill_count=0`
  - `remaining_size=0.00006489`

## 4. Expected open-hold semantics

- `position_size_base` is de beschikbare, niet-gereserveerde base
- `reserved_base_open_exit_orders` is de base die door open D.3 `SELL`-orders gereserveerd is
- `bot_managed_base` is `position_size_base + reserved_base_open_exit_orders`
- Zolang de open D.3 `SELL` geen fills heeft, mag die reservation niet verdwijnen
- Tiny-residual cleanup of inventory-sync mag een positie niet sluiten zolang een open D.3 exit-order nog aan dezelfde lifecycle hangt

Voor deze lifecycle betekent dat:

- available/unreserved base: `0.0000649067431275`
- reserved by open D.3 TP1: `0.00006489`
- total bot-managed base: `0.0001297967431275`

## 5. Reconstruction candidate

| field | current local value | proposed preview value | source/evidence | confidence | notes |
| --- | --- | --- | --- | --- | --- |
| ticker | `BTC-USDC` | `BTC-USDC` | `state/positions.json`, `state/open_orders.json` | high | Geen wijziging nodig |
| linked_position_id | niet als actief open-veld aanwezig in lokale positie; D.3 order verwijst naar `76310097-849e-481c-b587-ba44bc3330fe` | `76310097-849e-481c-b587-ba44bc3330fe` | open D.3 order, D.3 submit logs, governance commands | medium | Lokale position-store gebruikt nu ticker-key en `order_id=pos-1`; mapping vraagt expliciete recovery-keuze |
| status | `closed` | `open` | `state/positions.json` vs. `15:00Z` open-hold log snapshot | high | Kern van de reconstructiepreview |
| position_size_base | `0` | `0.0000649067431275` | `15:00Z` heartbeat/open-hold logs | high | Dit is de unreserved available base |
| bot_managed_base | `0` | `0.0001297967431275` | `15:00Z` heartbeat/open-hold logs en oorspronkelijke D.3 submit-evidence | high | Moet gelijk zijn aan available + reserved |
| reserved_base_open_exit_orders | niet als coherent open-reservation op de positie aanwezig | `0.00006489` | `state/open_orders.json`, live D.3 snapshot | high | Gelijk aan open `remaining_size` zolang geen fills |
| open_d3_exit_client_order_id | impliciet via open order store | `phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000` | `state/open_orders.json` | high | Moet aan de preview gekoppeld blijven |
| open_d3_exit_exchange_order_id | impliciet via open order store | `bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31` | `state/open_orders.json` | high | Mag niet worden vervangen |
| last_recovery_reason | `live_base_present_after_inventory_sync_tiny_residual_close` | behouden | `state/positions.json` | high | Historische recovery lineage niet wissen |
| recovery_preview_only | niet aanwezig | `true` | dit document | high | Expliciet markeren als preview-only, geen apply |

Metadata die in een latere recovery-preview behouden zou moeten blijven:

- `phase_c43_client_order_id`
- `phase_c43_exchange_order_id=76310097-849e-481c-b587-ba44bc3330fe`
- `partial_take_profit_taken=true`
- entry/fill/fee-provenance
- bestaande timestamps en recovery/close breadcrumbs
- het huidige open D.3 orderrecord zelf

Velden die in deze preview juist niet opnieuw geïnterpreteerd mogen worden als fill-evidence:

- `filled_base`
- `filled_quote`
- `fill_count`
- live `remaining_size`

## 6. Invariants before any future apply

- [ ] live order still `OPEN/open`
- [ ] `filled_base=0`
- [ ] `filled_quote=0`
- [ ] `fill_count=0`
- [ ] local open D.3 order exists
- [ ] no duplicate exit
- [ ] no negative base
- [ ] reconstructed `bot_managed_base == position_size_base + reserved_base_open_exit_orders`
- [ ] no live action
- [ ] no Coinbase cancel/replace
- [ ] human ACK required

## 7. Recovery options

### A. No action / keep diagnose-only

- Safety: highest
- Complexity: lowest
- Live risk: none
- State risk: mismatch blijft bestaan
- Recommended order: altijd valide als tijdelijke fail-closed keuze

### B. Local reconstruction apply with explicit ACK, later only

- Safety: medium-high mits dedicated preview/apply tooling en snapshots
- Complexity: medium
- Live risk: none direct, want lokaal-only
- State risk: medium; verkeerde reconstructie kan lifecycle-coherentie schaden
- Recommended order: beste inhoudelijke vervolgstap na extra preview-validatie

### C. Cancel-only route, later only

- Safety: medium
- Complexity: medium-high
- Live risk: hoger, want echte Coinbase cancel is nodig
- State risk: lager dan vrije recovery, maar vereist daarna coherent closeout
- Recommended order: pas overwegen als reconstructie niet vertrouwd wordt of operationeel eenvoudiger blijkt

### D. Full recovery tool design first

- Safety: high
- Complexity: highest
- Live risk: none tijdens ontwerp
- State risk: lowest vóór apply, omdat ontwerp eerst invarianten en tests kan borgen
- Recommended order: sterk aanbevolen vóór een echte recovery apply

## 8. Recommended next step

Veiligste vervolgstap is eerst een dedicated recovery preview/apply tool en testontwerp uitwerken, zonder apply uit te voeren.

Reden:

- de live D.3 lifecycle is nog open en heeft geen fills
- de mismatch is lokaal, niet live
- reconstructie is waarschijnlijk inhoudelijk correcter dan direct cancel-only
- een dedicated tool kan vooraf exacte snapshots, invarianten, veldmapping en rollback-/sanity-checks expliciet maken

Pas daarna komt eventueel in aanmerking:

1. extra read-only verificatie van de previewwaarden
2. een aparte sessie voor expliciete ACK op een recovery apply
3. alternatief: controlled cancel-only route als recovery niet vertrouwd wordt
