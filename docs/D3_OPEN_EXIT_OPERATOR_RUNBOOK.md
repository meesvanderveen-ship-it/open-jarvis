# D.3 Open Exit Operator Runbook

## Workflow consolidation note

`AGENTS.md` and `docs/CODEX_WORKFLOW.md` are the leading workflow instructions for future Codex sessions. The former active D.3/D.4 TP1 SELL `phased4-BTCUSDC-TP1-repl-bc3330fe-20260529175801` / `fd9f1d65-1623-4148-8bdd-c12ecf6d786d` at `74000.00` is filled and locally applied. The TP_CLOSE residual replacement SELL `phased3-BTCUSDC-TPCLOSE-repl-pos1-20260530215029` / `8bcafe10-d31c-4067-886d-324d0f284967` at `74000.00` is also filled and locally applied. There is currently no open D.3 exit order (`open_orders=0`, `open_d3_exit=0`). Current local BTC-USDC position state is closed with `position_size_base=0` and `bot_managed_base=0`. Derived/orderstore reservation governance reports `0`; `state/positions.json` still has stale denormalized `reserved_base_open_exit_orders=0.00006490`, and TP_CLOSE lifecycle fees are persisted as `0` while direct Coinbase fee evidence is `0.0288156`. Any repair, manual position close, TP2/runner/trailing, re-entry, cancel/replace/reprice, system package install, D.6-to-execution bridge or additional live order requires a separate exact ACK.

## 1. Purpose

Dit runbook is nu referentie/historische context voor D.3 open-exit lifecycles; er is momenteel geen open D.3 exit order.
Het doel is veilige bediening bij een toekomstige goedgekeurde `OPEN`, `PARTIAL`, `FILLED`, `CANCELLED`, `EXPIRED`, `REJECTED` of latere cancel/replace-candidate.
Dit document is geen toestemming voor live acties.

## 1A. Current lifecycle override

De actuele D.3/D.4 TP1 en TP_CLOSE lifecycles zijn afgerond als filled/applied. Oudere cancelled/open TP1-orders in dit document blijven historische context en mogen niet als actuele open lifecycle worden gebruikt.

- `ticker=BTC-USDC`
- `client_order_id=phased4-BTCUSDC-TP1-repl-bc3330fe-20260529175801`
- `exchange_order_id=fd9f1d65-1623-4148-8bdd-c12ecf6d786d`
- `linked_position_id=76310097-849e-481c-b587-ba44bc3330fe`
- `side=SELL`
- `exit_label=TP1`
- `size_base=0.00006489`
- `remaining_size=0`
- `limit_price=74000.00`
- `post_only=true`
- `reduce_only_local=true`
- local order status: `filled`
- local position status: `closed`
- open D.3 exit count: `0`
- derived reserved_base_open_exit_orders: `0`
- available_base_after_reservations: `0`
- duplicate/oversell: `false/false`
- latest Coinbase branch: `FILLED/filled`, filled_base `0.00006489`, filled_quote `4.80186000`, fee `0.02881116`

Actuele TP_CLOSE closure:

- `ticker=BTC-USDC`
- `client_order_id=phased3-BTCUSDC-TPCLOSE-repl-pos1-20260530215029`
- `exchange_order_id=8bcafe10-d31c-4067-886d-324d0f284967`
- `linked_position_id=pos-1`
- `side=SELL`
- `exit_label=TP_CLOSE`
- `size_base=0.00006490`
- `remaining_size=0`
- `limit_price=74000.00`
- local order status: `filled`
- local position status: `closed`
- open orders / open D.3 exits: `0` / `0`
- residual BTC: `0` in current local position state; earlier practical dust remains historical context only
- derived reserved_base_open_exit_orders: `0`
- stale denormalized position field: `reserved_base_open_exit_orders=0.00006490`
- latest Coinbase branch: `FILLED/filled`, filled_base `0.0000649`, filled_quote `4.8026000`, direct fee evidence `0.0288156`
- lifecycle persisted fees: `0`

## 1B. Trigger policy for future monitoring

Niet opnieuw monitoren zonder trigger. Er is momenteel geen open TP_CLOSE order. Een read-only lifecycle poll is alleen zinvol als minimaal een van deze triggers waar is:

- Future approved active lifecycle trigger: een nieuwe actieve order bestaat en de operator wil actuele status.
- Lifecycle trigger: Coinbase/UI/logs/alerts suggereren fill, partial fill, cancel, reject, expiry of statuswijziging.
- Safety trigger: local state drift, open D.3 exit count niet `0` zonder bekende actieve lifecycle, reservation mismatch, duplicate/oversell warning, of service/runtime issue.
- Explicit operator request: de operator vraagt expliciet om een nieuwe read-only statuscontrole.

Als geen trigger waar is:

- geen Coinbase poll
- geen live action
- geen state write
- geen lifecycle apply
- volgende productstap is `wachten tot trigger`

Als een poll wel gerechtvaardigd is:

- exact een read-only poll met `--allow-coinbase-poll`
- geen `--apply`
- geen ACK
- geen cancel/replace/submit
- bij `OPEN/open` met zero fills: `keep_open`
- bij `PARTIAL` of `FILLED`: stop voor `Controlled D.3 Lifecycle Apply on Fill Evidence v1` met aparte ACK
- bij `CANCELLED`, `EXPIRED` of `REJECTED`: stop voor `Controlled D.3 Terminal Closeout Reconcile v1` met aparte ACK
- D.4 trailing/cancel-replace pas ontwerpen nadat lifecycle apply/terminal closeout-routing stabiel is bewezen

## 2. Current live order

- `ticker=BTC-USDC`
- `client_order_id=phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000`
- `exchange_order_id=bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31`
- `linked_position_id=76310097-849e-481c-b587-ba44bc3330fe`
- `side=SELL`
- `exit_label=TP1`
- `limit_price=81664.97`
- `remaining_size=0.00006489`
- laatste bekende Coinbase-status:
  - `raw_status=CANCELLED`
  - `normalized_status=cancelled`
  - `filled_base=0`
  - `filled_quote=0`
  - `avg_fill_price=0`
  - `fill_count=0`
  - `evidence_hash=fa283d56ad9221ea03124e9bd5a229f281c2e4981dae09e23f1112f5515d7aac`
  - `evidence_timestamp=2026-05-28T15:12:46.102954+00:00`
  - `suggested_local_action=mark_cancelled`
- laatste bekende lokale status:
  - `local_order_status=cancelled/final`
  - `local_position_status=open`
  - `open_d3_exit_count=0`
  - `remaining_size=0`
  - `reserved_base_open_exit_orders=0`
  - `state_write_performed=true`
- interpretatie:
  - exchange-status is niet meer OPEN
  - lokale orderstatus is coherent bijgewerkt naar cancelled
  - reservation is vrijgegeven
  - positie blijft open
  - volgende stap is replacement/new-exit decision met aparte approval

## 3. Absolute safety rules

- geen live BUY
- geen tweede SELL
- geen retry
- geen cancel zonder aparte cancel-ACK
- geen replace zonder aparte replace-ACK
- geen reconcile apply zonder D.3 reconciliation ACK
- geen service restart
- geen `.env`-mutatie
- geen recovery apply
- geen state mutation bij `OPEN/open`

## 4. Normal OPEN/open branch

- draai alleen read-only:
  - snapshot
  - reconcile dry-run
  - governance previews
- bij `keep_open`:
  - niets doen
  - geen apply
  - geen cancel
  - geen replace
- geen herhaalde monitorloop
- pas opnieuw checken bij:
  - later tijdstip
  - duidelijke marktbeweging
  - statuswijziging

## 5. PARTIAL branch

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
- na apply:
  - geen nieuwe SELL
  - eerst D.2/D.3 alleen preview-only

## 6. FILLED branch

- eerst snapshot + reconcile dry-run
- controleer:
  - full TP1 completion
  - reservation release
  - position/base update
- apply alleen met D.3 reconciliation ACK
- daarna:
  - D.2 status read-only controleren
  - TP2/runner alleen preview-only

## 7. CANCELLED / EXPIRED / REJECTED branch

- eerst snapshot + reconcile dry-run
- controleer:
  - closeout / reject proposal
  - reservation release
  - dat de positie coherent blijft
- geen nieuwe SELL vóór closeout coherent is
- apply alleen met D.3 reconciliation ACK
- huidige branch sinds `2026-05-28T15:12:46Z`:
  - Coinbase evidence: `CANCELLED`
  - fills: `0`
  - proposed local action: `mark_cancelled`
  - lokale closeout/reconcile toegepast om `2026-05-28T15:20:54Z`
  - old D.3 order local status: `cancelled`
  - open D.3 exit count: `0`
  - reservation: `0`
  - geen replacement plaatsen zonder aparte replacement/new-exit approval

## 8. Cancel candidate branch

- geen cancel direct uitvoeren
- aparte controlled cancel-only sessie
- required ACK:
  - `I_UNDERSTAND_AND_APPROVE_D3_OPEN_EXIT_CANCEL_GOVERNANCE`
- na cancel:
  - poll tot `CANCELLED`
  - local closeout dry-run
  - local closeout apply alleen met D.3 reconciliation ACK

## 9. Replace candidate branch

- geen atomic cancel+replace
- sequence:
  1. controlled cancel-only
  2. poll tot `CANCELLED`
  3. local closeout dry-run
  4. local closeout apply met ACK
  5. nieuwe D.3 preview
  6. fingerprint review
  7. nieuwe one-shot SELL alleen met aparte expliciete approval

## 10. Minimal command reference

Alleen read-only commands:

```bash
# read-only: audit
PYTHONPATH=. .venv/bin/python tools/show_function_preservation_audit.py --fail-on-review

# read-only: C.4.3 status
PYTHONPATH=. .venv/bin/python tools/show_phase_c43_autonomous_entry_live.py \
  --ticker BTC-USDC \
  --order-store state/open_orders.json \
  --json

# read-only: D.3 live snapshot
PYTHONPATH=. .venv/bin/python tools/show_phase_d3_live_exit_order_snapshot.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --json

# read-only: D.3 reconcile dry-run
PYTHONPATH=. .venv/bin/python tools/reconcile_phase_d3_live_exit_order.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --dry-run \
  --json

# read-only: D.3 open-exit governance
PYTHONPATH=. .venv/bin/python tools/show_phase_d3_open_exit_order_governance.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --json

# read-only: D.3 cancel/replace governance
PYTHONPATH=. .venv/bin/python tools/show_phase_d3_cancel_replace_governance.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --json

# read-only: D.3 lifecycle manager v1 local preview
PYTHONPATH=. .venv/bin/python tools/run_phase_d3_open_exit_lifecycle_manager.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --json
```

Niet uitvoeren in deze ronde:

ACK/live commands:
- Niet uitvoeren zonder aparte menselijke toestemming.

## 11. D.3 Open Exit Lifecycle Manager v1

Doel:
- één centrale preview/apply-local tool voor de bestaande open D.3 SELL lifecycle
- geen Coinbase submit/cancel/replace
- geen orderstatus- of fillfabricatie
- apply-local alleen voor lokale coherentie op echte lifecycle-evidence

Tool:
- `tools/run_phase_d3_open_exit_lifecycle_manager.py`

Preview-only default:
- geen state write
- geen Coinbase call zonder `--allow-coinbase-poll`
- verwachte lokale preview zonder poll:
  - `status=d3_open_exit_lifecycle_preview_ready`
  - `proposed_action=keep_local_open_no_live_snapshot`
  - `coinbase_call_attempted=false`
  - `state_write_performed=false`

Apply-local alleen met ACK:
- `--apply-local`
- ACK:
  - `I_UNDERSTAND_AND_APPROVE_D3_OPEN_EXIT_LIFECYCLE_APPLY`

## 12. Three operator modes

1. Local preview zonder Coinbase:

```bash
PYTHONPATH=. .venv/bin/python tools/run_phase_d3_open_exit_lifecycle_manager.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --json
```

- geen Coinbase call
- geen state write
- bij coherente lokale state:
  - `status=d3_open_exit_lifecycle_preview_ready`
  - `proposed_action=keep_local_open_no_live_snapshot`

2. Read-only Coinbase evidence poll:

```bash
PYTHONPATH=. .venv/bin/python tools/run_phase_d3_open_exit_lifecycle_manager.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --allow-coinbase-poll \
  --json
```

- alleen read-only order/fill evidence
- geen state write
- geen submit/cancel/replace
- DNS/runtime/network failure:
  - rapporteren
  - stoppen
  - geen live retry/cancel/replace/apply

3. Controlled local apply met ACK:

```bash
PYTHONPATH=. .venv/bin/python tools/run_phase_d3_open_exit_lifecycle_manager.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --allow-coinbase-poll \
  --apply-local \
  --apply-ack I_UNDERSTAND_AND_APPROVE_D3_OPEN_EXIT_LIFECYCLE_APPLY \
  --json
```

- alleen lokale state/order update
- nooit Coinbase submit/cancel/replace

## 13. D.3 Open Exit Monitor & Operator Decision Layer v1

Doel:
- de open TP1 exit niet alleen pollen, maar productmatig bewaken
- exact tonen wat de volgende toegestane operatoractie is
- expliciet tonen welke acties verboden blijven
- geen state writes
- geen lifecycle apply
- geen submit/cancel/replace

Tool:
- `tools/show_phase_d3_open_exit_monitor.py`

Local-only monitor:

```bash
PYTHONPATH=. .venv/bin/python tools/show_phase_d3_open_exit_monitor.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --json
```

Read-only Coinbase monitor:

```bash
PYTHONPATH=. .venv/bin/python tools/show_phase_d3_open_exit_monitor.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --allow-coinbase-poll \
  --json
```

Monitoruitkomst lezen:
- `operator_decision`
- `next_allowed_action`
- `next_forbidden_actions`
- `priority_classification`
- `stale_open_classification`
- `recommended_next_check`

## 14. Operator decision matrix

1. Local coherent zonder Coinbase poll
- `status=open_exit_monitor_local_coherent`
- `operator_decision=keep_monitoring`
- `next_allowed_action=read_only_coinbase_poll_later`
- verboden:
  - `submit`
  - `cancel`
  - `replace`
  - `sell`
  - `apply`

2. Local coherent + Coinbase OPEN
- `status=open_exit_monitor_coinbase_open`
- `operator_decision=keep_open_and_monitor`
- toegestane volgende stap:
  - later opnieuw read-only poll
  - stale-open review als leeftijd dat vraagt
- verboden:
  - `apply`
  - `cancel`
  - `replace`
  - `sell`

3. Local position drift
- `status=open_exit_monitor_local_position_drift`
- `operator_decision=recovery_required_if_coinbase_open`
- eerst:
  - read-only Coinbase poll
  - pas daarna recovery preview/apply route
- verboden:
  - `cancel`
  - `replace`
  - `sell`
  - lifecycle apply op niet-bevestigde evidence

4. Coinbase PARTIAL / FILLED / CANCELLED / EXPIRED / REJECTED
- `status=open_exit_monitor_lifecycle_evidence_available`
- `operator_decision=await_explicit_lifecycle_apply_approval`
- toegestane volgende stap:
  - aparte ACK-gestuurde D.3 lifecycle apply sessie
- verboden:
  - auto apply
  - `cancel`
  - `replace`
  - `sell`

5. Coinbase poll failure
- `status=open_exit_monitor_coinbase_poll_failed`
- `operator_decision=retry_later_or_use_outside_sandbox_read_only_poll`
- geen live workaround
- geen submit/cancel/replace

6. Duplicate / oversell / safety mismatch
- `status=open_exit_monitor_blocked_review_required`
- alleen manual review
- geen live actie

## 15. Stale-open review

Stale-open review is nog geen cancel/replace-automation.
Het is alleen een operatorreview-signaal.

Leeftijdsregels:
- `<30 min`: `normal_monitoring`
- `30-120 min`: `stale_watch`
- `>120 min`: `stale_open_review_recommended`
- onbekend: `stale_age_unknown`

Betekenis:
- `stale_watch`:
  - monitor later opnieuw
- `stale_open_review_recommended`:
  - mogelijke toekomstige branch:
    - `Controlled D.3 Cancel/Replace Review v1`
  - niet automatisch cancelen
  - niet automatisch replacen

## 16. Current recommended operator posture

Actuele productmatige houding voor de open BTC-USDC TP1:
- open exit lifecycle blijft actief
- lokale positie en reservation zijn coherent
- standaard volgende stap:
  - `keep_monitoring`
- toegestane operatoractie:
  - later opnieuw read-only poll
  - stale-open review als leeftijd/marktcontext dat vraagt
- verboden zonder aparte approval:
  - D.3 lifecycle apply
  - cancel
  - replace
  - nieuwe SELL

## 17. Controlled D.3 Stale-Open Review v1

Doel:
- stale open TP1-orders apart beoordelen zonder live actie
- bepalen of de route nog `keep_open_and_monitor` is
- of een latere `Controlled D.3 Cancel/Replace Review v1` productmatig voorbereid moet worden
- of non-OPEN evidence eerst naar controlled lifecycle apply moet

Tool:
- `tools/show_phase_d3_stale_open_review.py`

Local-only stale review:

```bash
PYTHONPATH=. .venv/bin/python tools/show_phase_d3_stale_open_review.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --json
```

Read-only Coinbase stale review:

```bash
PYTHONPATH=. .venv/bin/python tools/show_phase_d3_stale_open_review.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --allow-coinbase-poll \
  --json
```

## 18. Stale-open review decision matrix

1. Local-only stale review, coherent open state, `stale_open_review_recommended`
- `status=stale_open_review_local_only_ready`
- `stale_review_decision=read_only_coinbase_poll_recommended_before_any_action`
- `recommended_operator_branch=run_one_read_only_coinbase_poll`
- toegestane volgende stap:
  - precies één read-only Coinbase poll
- verboden:
  - `submit`
  - `cancel`
  - `replace`
  - `sell`
  - `apply`

2. Coinbase OPEN bevestigd
- `status=stale_open_review_coinbase_open`
- `stale_review_decision=prepare_cancel_replace_review_later`
- `recommended_operator_branch=Controlled D.3 Cancel/Replace Review v1`
- dit is alleen voorbereiding
- niet uitvoeren:
  - direct cancel
  - direct replace
  - nieuwe SELL
  - lifecycle apply

3. Coinbase PARTIAL / FILLED / CANCELLED / EXPIRED / REJECTED
- `status=stale_open_review_lifecycle_evidence_available`
- `stale_review_decision=await_explicit_d3_lifecycle_apply_approval`
- `recommended_operator_branch=Controlled D.3 lifecycle apply on real evidence`
- geen auto-apply

4. Local position drift
- `status=stale_open_review_local_position_drift`
- `stale_review_decision=recovery_required_if_coinbase_open`
- eerst:
  - read-only Coinbase poll
  - dan pas recovery preview/apply route als `OPEN` bevestigd is

5. Coinbase poll failure
- `status=stale_open_review_coinbase_poll_failed`
- `stale_review_decision=retry_later_or_use_outside_sandbox_read_only_poll`
- geen retry storm
- geen live workaround
- buiten-sandbox read-only poll alleen met expliciete operatorgoedkeuring

6. Duplicate / oversell / safety mismatch
- `status=stale_open_review_blocked_review_required`
- alleen manual review
- geen live actie

## 19. Controlled D.3 Cancel/Replace Review v1

Doel:
- read-only beoordelen of de huidige stale OPEN TP1 later in aanmerking komt voor een aparte cancel/replace-pilot
- geen live cancel
- geen live replace
- geen nieuwe SELL
- geen lifecycle apply

Tool:
- `tools/show_phase_d3_cancel_replace_review.py`

Local-only review:

```bash
PYTHONPATH=. .venv/bin/python tools/show_phase_d3_cancel_replace_review.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --json
```

Optionele read-only Coinbase review:

```bash
PYTHONPATH=. .venv/bin/python tools/show_phase_d3_cancel_replace_review.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --allow-coinbase-poll \
  --json
```

Future ACK alleen voor latere pilot:
- `I_UNDERSTAND_AND_APPROVE_D3_CANCEL_REPLACE_PILOT`

## 20. Cancel/replace review decision matrix

1. Coherent local-only review zonder verse Coinbase OPEN evidence
- `status=cancel_replace_review_needs_fresh_open_evidence`
- `cancel_replace_decision=run_one_read_only_coinbase_poll_before_pilot`
- toegestane volgende stap:
  - één read-only Coinbase poll
- verboden:
  - `direct_cancel`
  - `direct_replace`
  - `new_sell`
  - `lifecycle_apply`
  - `submit`

2. Coherent + Coinbase OPEN
- `status=cancel_replace_review_ready`
- `cancel_replace_decision=prepare_cancel_replace_pilot`
- `candidate_cancel_allowed_in_future=true`
- `candidate_replace_allowed_in_future=true`
- `required_future_ack=I_UNDERSTAND_AND_APPROVE_D3_CANCEL_REPLACE_PILOT`
- nog steeds niet uitvoeren:
  - direct cancel
  - direct replace
  - nieuwe SELL

3. Coinbase PARTIAL / FILLED / CANCELLED / EXPIRED / REJECTED
- `status=cancel_replace_review_not_applicable_lifecycle_evidence_available`
- `cancel_replace_decision=route_to_controlled_lifecycle_apply`
- geen cancel/replace

4. Local position drift
- `status=cancel_replace_review_blocked_local_position_drift`
- `cancel_replace_decision=recovery_required_if_coinbase_open`
- eerst recovery-branch, geen cancel/replace

5. Duplicate / oversell / safety mismatch
- `status=cancel_replace_review_blocked_safety`
- alleen manual review
- geen live actie

6. Coinbase poll failure
- `status=cancel_replace_review_coinbase_poll_failed`
- `next_allowed_action=read_only_coinbase_poll_later_or_outside_sandbox`
- geen retry storm
- geen live workaround
- apply alleen bij coherente evidence
- zonder ACK:
  - block
- met onbekende status of mismatch:
  - block

## 13. Lifecycle manager status/action matrix

Bij lokale preview zonder live snapshot:
- `normalized_status=local_only_open`
- `proposed_action=keep_local_open_no_live_snapshot`
- positie en reservation blijven intact

Bij echte Coinbase evidence via fixture of expliciete `--allow-coinbase-poll`:
- `OPEN`
  - `proposed_action=keep_open`
  - order blijft `submitted/open`
  - positie blijft `open`
  - reservation blijft intact
  - apply-local is no-op
- `PARTIAL`
  - `proposed_action=mark_partially_filled`
  - alleen lokale fill/reservation update op echte fill-evidence
  - alleen nieuwe delta verwerken
  - herhaling van exact dezelfde evidence is no-op
- `FILLED`
  - `proposed_action=mark_filled`
  - lokale order finaliseren
  - positie reduceren/sluiten conform evidence
  - reservation vrijgeven
  - herhaling van exact dezelfde evidence is no-op
- `CANCELLED`
  - `proposed_action=mark_cancelled`
  - lokale order finaliseren
  - reservation vrijgeven
  - positie coherent open houden met resterende base
- `EXPIRED`
  - `proposed_action=mark_expired`
  - zelfde closeout-pad als cancelled, zonder fill
- `REJECTED`
  - `proposed_action=mark_rejected`
  - zelfde closeout-pad als cancelled, zonder fill
- onbekend of mismatch
  - `status=blocked_review_required`
  - geen write

## 14. Safety invariants now enforced

- open D.3 exit reservation voorkomt tiny-residual/inventory-sync close
- linked position lineage gebruikt:
  - `recovery_linked_position_id`
  - `phase_c43_exchange_order_id`
  - `position_id`
  - `order_id`
- duplicate open D.3 exits voor dezelfde logische positie blokkeren lifecycle apply
- oversell detectie blokkeert wanneer reserved base groter wordt dan managebare base
- `REPLICATION_ENABLED=true` blijft fail-closed voor local apply tooling
- apply zonder echte evidence blokkeert
- partial/filled zonder fill-evidence blokkeert
- cancelled/expired/rejected met onverwachte fill-evidence blokkeert
- lifecycle idempotency metadata voorkomt dubbele base-reductie
- geen cancel/replace/SELL zonder aparte approval

## 15. Decision rules

- `OPEN`
  - niets toepassen
  - order blijft open
  - geen cancel/replace/SELL
- `PARTIAL`
  - apply alleen met ACK als evidence coherent is
  - daarna D.2/D.3 alleen preview-only
- `FILLED`
  - apply alleen met ACK als evidence coherent is
  - daarna D.2 status en vervolg-preview read-only
- `CANCELLED/EXPIRED/REJECTED`
  - apply alleen met ACK om reservation lokaal vrij te geven
  - geen nieuwe SELL vóór coherente closeout
- `unknown`
  - stoppen
  - geen apply

Als lokale preview toont dat de positie lokaal weer `closed/zero` staat terwijl de D.3 order nog open is:
- eerst recovery preview/apply route beoordelen
- geen SELL/cancel/replace als workaround
- geen handmatige state repair buiten de recovery/lifecycle tools

Niet toegestaan zonder aparte approval:
- Coinbase cancel
- Coinbase replace
- nieuwe SELL
- tweede SELL
- retry submit

## 16. End-of-session checklist

- status genoteerd
- geen ongewenste live actie
- geen state mutation bij `OPEN`
- Markdown checkpoint toegevoegd
- volgende branch duidelijk

## 17. Controlled D.3 Cancel/Replace Pilot Preflight v1

Doel:
- na verse OPEN-evidence bepalen of een toekomstige controlled cancel/replace-pilot veilig voorbereid kan worden
- alleen review/preflight
- geen live cancel
- geen live replace
- geen nieuwe SELL
- geen lifecycle apply

Tool:
- `tools/show_phase_d3_cancel_replace_pilot_preflight.py`

Local-only preflight:

```bash
PYTHONPATH=. .venv/bin/python tools/show_phase_d3_cancel_replace_pilot_preflight.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --json
```

Read-only Coinbase preflight poll:

```bash
PYTHONPATH=. .venv/bin/python tools/show_phase_d3_cancel_replace_pilot_preflight.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --allow-coinbase-poll \
  --json
```

Future ACK voor een latere pilot, niet gebruiken in deze ronde:
- `I_UNDERSTAND_AND_APPROVE_D3_CANCEL_REPLACE_PILOT`

Preflightmatrix:

1. Local-only zonder verse OPEN-evidence
- `status=cancel_replace_pilot_preflight_needs_fresh_open_evidence`
- `preflight_decision=run_one_read_only_coinbase_poll_before_pilot`
- `pilot_candidate_ready=false`
- toegestane volgende stap:
  - `read_only_coinbase_poll`

2. Coinbase OPEN + local coherent + prijs beschikbaar
- `status=cancel_replace_pilot_preflight_ready`
- `preflight_decision=ready_for_explicit_cancel_replace_pilot_approval`
- `pilot_candidate_ready=true`
- `cancel_leg_ready=true`
- `replace_leg_ready=true`
- preview-only kandidaat:
  - `candidate_cancel_order_id=<exchange_order_id>`
  - `candidate_cancel_client_order_id=<client_order_id>`
  - `candidate_replace_side=SELL`
  - `candidate_replace_size_base=<remaining_size>`
  - `candidate_replace_limit_price=<existing_limit_price_or_fresh_context>`
  - `candidate_replace_post_only=true`
  - `candidate_replace_reduce_only_semantic=true`
- nog steeds verboden:
  - live cancel
  - live replace
  - nieuwe SELL

3. Coinbase OPEN + local drift
- `status=cancel_replace_pilot_preflight_blocked_local_position_drift`
- `preflight_decision=recovery_required_if_coinbase_open`
- eerst recovery preview, daarna alleen indien groen en expliciet toegestaan recovery apply
- pas daarna opnieuw local-only preflight

4. Coinbase non-OPEN evidence
- `status=cancel_replace_pilot_preflight_not_applicable_lifecycle_evidence_available`
- `preflight_decision=route_to_controlled_lifecycle_apply`
- geen cancel/replace-pilot
- volgende stap:
  - aparte `Controlled D.3 lifecycle apply`-ronde met expliciete approval

5. Duplicate / oversell / reservation mismatch
- `status=cancel_replace_pilot_preflight_blocked_safety`
- geen live actie
- alleen manual review

6. Coinbase poll failure
- `status=cancel_replace_pilot_preflight_coinbase_poll_failed`
- `preflight_decision=retry_later_or_use_outside_sandbox_read_only_poll`
- geen retry-storm
- geen live workaround

## 18. D.3 Local Drift Root-Cause Guard v1

Doel:
- voorkomen dat lokale cleanup-, inventory-sync-, heartbeat- of tiny-residual-routes een positie op `closed/zero` zetten zolang er een open D.3 exit-reservation bestaat
- centrale state-write guard, geen live actie

Guardgedrag:
- blokkeert local close/zero als:
  - ticker matcht
  - een open D.3 SELL-reservation bestaat
  - `remaining_size > 0`
  - de mutatie naar `status=closed`, `position_size_base=0`, `bot_managed_base=0` of `closed_at/close_time` zou gaan
- laat alleen gecontroleerde D.3 lifecycle-finalisatie toe wanneer de caller expliciet `controlled_d3_lifecycle_apply` is en er coherente terminal/fill evidence is

Operatorimpact:
- een terugkerende lokale drift mag niet meer stilletjes een open TP1-lifecycle breken
- recovery-tooling blijft beschikbaar voor reeds ontstane drift, maar hoort na deze guard niet meer de normale route te zijn
- geen live cancel/replace/SELL als workaround voor lokale drift

## 19. Controlled D.3 Cancel/Replace Pilot v1

Doel:
- een ACK-gestuurde pilottool die een bestaande stale OPEN D.3 TP1 exit alleen gecontroleerd kan cancellen en vervangen
- default altijd preview-only
- zonder ACK geen Coinbase cancel, geen Coinbase replace, geen Coinbase submit en geen state mutation

Tool:
- `tools/run_phase_d3_cancel_replace_pilot.py`

Preview-only:

```bash
PYTHONPATH=. .venv/bin/python tools/run_phase_d3_cancel_replace_pilot.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --json
```

Armed live pilot, alleen in een aparte goedgekeurde operatorsessie:

```bash
PYTHONPATH=. .venv/bin/python tools/run_phase_d3_cancel_replace_pilot.py \
  --ticker BTC-USDC \
  --client-order-id phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000 \
  --exchange-order-id bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31 \
  --linked-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --allow-coinbase-poll \
  --allow-live-cancel \
  --allow-live-replace \
  --pilot-ack I_UNDERSTAND_AND_APPROVE_D3_CANCEL_REPLACE_PILOT \
  --json
```

Gates:
- exacte ACK:
  - `I_UNDERSTAND_AND_APPROVE_D3_CANCEL_REPLACE_PILOT`
- vereiste live flags:
  - `--allow-coinbase-poll`
  - `--allow-live-cancel`
  - `--allow-live-replace`
- zonder een van deze gates:
  - geen live actie
  - geen state mutation

Pilotflow:
1. draai altijd eerst preflight
2. alleen bij `cancel_replace_pilot_preflight_ready` mag live mode verder
3. live pilot cancelt eerst exact de bestaande TP1 order
4. alleen bij coherente cancel mag replacement SELL volgen
5. replacement moet:
- `side=SELL`
- `size_base <= remaining_size`
- `post_only=true`
- lokale reduce-only semantiek behouden
- geen duplicate open D.3 exit veroorzaken
- geen oversell veroorzaken
6. lokale state mag pas worden geüpdatet als replacement-submit coherent terugkomt

Fail-closed regels:
- cancel failure:
  - stop
  - geen replacement
- cancel onzeker:
  - stop
  - geen replacement
- replacement failure:
  - geen tweede replacement
  - handmatige review vereist
- non-OPEN lifecycle evidence:
  - geen cancel/replace-pilot
  - route naar aparte lifecycle-apply approval

Verboden, ook met ACK:
- nieuwe BUY
- market SELL
- taker replacement
- tweede onafhankelijke SELL
- replacement groter dan `remaining_size`
- lifecycle apply in dezelfde pilot
- follower/replication

## 20. Checkpoint: D.3 Local Drift Guard v2 implemented

- timestamp: `2026-05-26T20:19:18Z`
- root-cause/meest waarschijnlijke route:
  - inventory-sync tiny-residual close-route zette `BTC-USDC` opnieuw op `closed/zero`
  - `logs/inventory_sync.jsonl` liet daarna elk uur `closed=["BTC-USDC"]` zien ondanks de nog open TP1 SELL
  - de gesloten positie miste guardmetadata, dus de actieve runtime heeft waarschijnlijk nog oudere code gedraaid; geen restart in deze ronde
- guard v2 inhoud:
  - bredere match op `linked_position_id`, `recovery_linked_position_id`, `phase_c43_exchange_order_id`, `order_id`, `source_order_id`, `source_client_order_id`, `replacement_of_client_order_id`, `replacement_of_exchange_order_id`
  - ticker-fallback alleen als de positie zelf geen bruikbare id-candidates heeft en exact één open D.3 SELL bestaat
  - block write zet nu expliciet:
    - `last_guard_version=v2`
    - `last_guard_checked_at`
    - `last_guard_match_strategy`
    - `last_guard_matching_order_ids`
    - `last_guard_total_reserved_open_exit_base`
    - `last_guard_attempted_*`
    - `last_guard_caller_reason`
- runtime sanity na patch:
  - recovery preview: `d3_local_position_recovery_preview_ready`
  - recovery apply: `d3_local_position_recovery_applied`
  - local-only cancel/replace preview:
    - `status=cancel_replace_pilot_preview_blocked`
    - `preflight_status=cancel_replace_pilot_preflight_needs_fresh_open_evidence`
    - geen `local_position_drift`
  - guard report:
    - `should_block_close=true`
    - `guard_status=guard_blocked_open_d3_exit_reservation`
    - `last_guard_match_strategy=linked_position_id`
- actuele lokale state:
  - positie:
    - `status=open`
    - `position_size_base=0.0000649067431275`
    - `bot_managed_base=0.0001297967431275`
    - `reserved_base_open_exit_orders=0.00006489`
  - D.3 order:
    - `status=submitted`
    - `remaining_size=0.00006489`
- uitgevoerde safety-actie:
  - geen Coinbase call
  - geen live actie
  - audit: `ok_observe_only`
- volgende operatorstap:
  - terug naar `Controlled D.3 Live Pilot Arming Decision`
  - alleen verder als de lokale positie open/coherent blijft
  - een volgende read-only Coinbase poll mag hooguit verse `OPEN/open` evidence bevestigen; geen cancel/replace of live arming in dezelfde sessie

## 21. Controlled D.3 Replacement / New Exit Decision v1

Current posture after cancel closeout:
- oude TP1 is lokaal `cancelled`
- positie is `open`
- `reserved_base_open_exit_orders=0`
- open D.3 exit count is `0`
- er is dus geen cancel/replace-route meer actief; de volgende stap is een nieuwe controlled D.3 exit decision

Read-only decision outcome:
- D.2 status: `position_executor_plan_ready_no_live_exit_submit`
- D.3 status: `d3_controlled_exit_ready_no_submit`
- decision branch: `new_exit_ready_awaiting_approval`
- candidate:
  - side: `SELL`
  - label: `TP1`
  - size_base: `0.000064898371563750`
  - limit_price: `84800.000`
  - estimated_quote_value: `5.503381908606000000000`
  - post_only: `true`
  - reduce_only_local: `true`
- reservation governance:
  - available_base_after_reservations: `0.0001297967431275`
  - reserved_base_open_exit_orders: `0`
  - open_exit_orders_count: `0`
  - duplicate/oversell: `false/false`
  - min_order_quote: `1.00`
  - min_size_ready: `true`

Forbidden in the decision-only round:
- geen Coinbase submit
- geen live SELL
- geen live arming
- geen state mutation
- geen lifecycle apply
- geen service restart

Required approvals/ACKs for a later new-exit submit round:
- round-level operator approval:
  - `I_APPROVE_CONTROLLED_D3_NEW_EXIT_SUBMIT_FOR_OPEN_BTC_POSITION`
- one-shot arm ACK:
  - `I_UNDERSTAND_THIS_ARMS_ONE_BTC_USDC_TP1_REDUCE_ONLY_LIVE_SELL_ONLY`
- D.3 human ACK:
  - `I_UNDERSTAND_AND_APPROVE_D3_CONTROLLED_REDUCE_ONLY_LIVE_EXITS`

Pre-submit gates for the later round:
1. service remains `active/running` from `/root/apps/Crypto/coinbase_bot`
2. local position remains `open`
3. open D.3 exit count remains `0`
4. reservation remains `0`
5. D.2 plan/fingerprint is accepted for this one-shot submit
6. D.3 readiness has no product blockers
7. candidate `size_base <= available_base_after_reservations`
8. `post_only=true` and local reduce-only semantics remain present
9. duplicate/oversell remain `false/false`
10. function preservation audit remains `ok_observe_only`

Command template for later use only after those gates and explicit approvals:

```bash
ENABLE_LIVE_EXIT_ORDERS=true \
AUTONOMOUS_ALLOW_EXITS=true \
ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=true \
PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=false \
REPLICATION_ENABLED=false \
ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false \
PYTHONPATH=. .venv/bin/python tools/run_phase_d3_controlled_exit_pilot.py \
  --ticker BTC-USDC \
  --submit-live \
  --one-shot-actual-exit-submit \
  --one-shot-arm-ack I_UNDERSTAND_THIS_ARMS_ONE_BTC_USDC_TP1_REDUCE_ONLY_LIVE_SELL_ONLY \
  --d3-human-ack I_UNDERSTAND_AND_APPROVE_D3_CONTROLLED_REDUCE_ONLY_LIVE_EXITS \
  --require-position-id 76310097-849e-481c-b587-ba44bc3330fe \
  --require-plan-fingerprint 769af186e97ca3b61ae63bc675be5831afda01026cb2697fa69969ef38f8d6f5 \
  --json
```

Fail-closed routing:
- if an open D.3 exit appears before submit: stop and route to duplicate/reconciliation review
- if D.2/D.3 candidate changes materially: stop and redo decision
- if Coinbase submit fails/rejects: no retry storm; inspect exact status and route to targeted recovery
- if submit succeeds: monitor the new D.3 exit and lifecycle evidence; apply lifecycle only in a separate ACK-gated round

## 22. Controlled D.3 New Exit Submit v1 result

Timestamp:
- `2026-05-28T15:35:41Z`

Outcome:
- one-shot live submit runner was executed exactly once with the required approvals/ACKs
- the runner stopped before Coinbase submit
- no live SELL was placed
- no state write occurred
- no retry was executed

Reason:
- pre-submit local/fallback D.2 fingerprint matched the approved fingerprint:
  - `769af186e97ca3b61ae63bc675be5831afda01026cb2697fa69969ef38f8d6f5`
- during the one-shot runner, Coinbase live product rules were fetched read-only:
  - base_increment: `1E-8`
  - price_increment: `0.01`
  - min_order_quote: `1`
- this changed the rounded D.2/D.3 candidate and fingerprint:
  - selected_plan_fingerprint: `d1d483d1a64e9e110296781a6f8228aa89260346b949162543a391cf80f1c8dd`
  - size_base: `0.00006489`
  - limit_price: `84800.00`
  - estimated_quote_value: `5.5026720000`
- blocker:
  - `d3_pilot_plan_fingerprint_mismatch`

Current local posture after fail-closed stop:
- local position: `open`
- open D.3 exit count: `0`
- reservation: `0`
- duplicate/oversell: `false/false`
- audit: `ok_observe_only`
- service: `active/running`

Operator rule from this result:
- do not rerun submit with the old fingerprint
- do not bypass fingerprint guard
- next round must first revalidate D.2/D.3 readiness using live Coinbase product rules context
- only after a new decision checkpoint may a later submit round use:
  - the new accepted fingerprint
  - fresh local sanity
  - fresh no-duplicate/no-oversell checks
  - fresh explicit approval

Next product step:
- `Targeted D.3 Live-Rule Fingerprint Revalidation v1`
- read-only only until the new live-rule fingerprint and rounded candidate are explicitly accepted

## 23. Targeted D.3 Live-Rule Fingerprint Revalidation v1

Timestamp:
- `2026-05-28T15:39:46Z`

Read-only result:
- live-rule preview reproduced the blocked runner context without submit
- command used:
  - `tools/run_phase_d3_controlled_exit_pilot.py --ticker BTC-USDC --use-live-exchange-rules-preview --require-position-id 76310097-849e-481c-b587-ba44bc3330fe --json`
- `submit_live=false`
- `live_submission_attempted=false`
- `live_order_submitted=false`
- no state write
- no Coinbase write action

Accepted live-rule candidate:
- accepted fingerprint:
  - `d1d483d1a64e9e110296781a6f8228aa89260346b949162543a391cf80f1c8dd`
- side: `SELL`
- label: `TP1`
- size_base: `0.00006489`
- limit_price: `84800.00`
- estimated_quote_value: `5.5026720000`
- post_only: `true`
- reduce_only_local: `true`
- position_id: `76310097-849e-481c-b587-ba44bc3330fe`

Product rules used:
- context: `coinbase_live_product_rules`
- base_increment: `1E-8`
- price_increment: `0.01`
- quote_increment: `0.01`
- min_order_quote: `1`

Diff from local/fallback candidate:
- old fingerprint:
  - `769af186e97ca3b61ae63bc675be5831afda01026cb2697fa69969ef38f8d6f5`
- old size/price/quote:
  - `0.000064898371563750`
  - `84800.000`
  - `5.503381908606000000000`
- live-rule size/price/quote:
  - `0.00006489`
  - `84800.00`
  - `5.5026720000`
- explanation:
  - base rounded to Coinbase `1E-8`
  - price rounded to Coinbase `0.01`
  - no strategy/position/side/label/post-only/reduce-only semantic change

Safety state:
- local position: `open`
- open D.3 exit count: `0`
- reservation: `0`
- duplicate/oversell: `false/false`
- min-size/min-quote: green
- audit: `ok_observe_only`

Next submit rule:
- do not use the old fingerprint for live submit
- next submit round must require:
  - `d1d483d1a64e9e110296781a6f8228aa89260346b949162543a391cf80f1c8dd`
- next submit round still requires:
  - fresh local sanity
  - fresh no-duplicate/no-oversell check
  - explicit round-level approval
  - one-shot arm ACK
  - D.3 human ACK
  - exact one submit attempt
  - no retry storm

Next product step:
- `Controlled D.3 New Exit Submit v2`

## 24. Controlled D.3 New Exit Submit v2 pre-submit blocked

Timestamp:
- `2026-05-28T16:21:46Z`

Outcome:
- pre-submit local sanity: green
- service freshness: active/running, PID `881456`, WorkingDirectory `/root/apps/Crypto/coinbase_bot`
- live-rule preview-only check succeeded host-side
- live submit uitgevoerd: `nee`
- Coinbase submit attempted: `false`
- state_write_performed: `false`

Stop reason:
- required accepted fingerprint:
  - `d1d483d1a64e9e110296781a6f8228aa89260346b949162543a391cf80f1c8dd`
- observed live-rule preview fingerprint:
  - `03369854182ca611df0c9a016c1d6208b27707c238976bd90fd2f8701c8dbba4`
- branch:
  - `accepted_live_rule_fingerprint_mismatch`
  - blocked before live submit

Observed live-rule candidate:
- side: `SELL`
- label: `TP1`
- execution_action: `place_limit_sell`
- size_base: `0.00006489`
- limit_price: `84800.00`
- estimated_quote_value: `5.5026720000`
- post_only: `true`
- reduce_only_local: `true`
- position_id: `76310097-849e-481c-b587-ba44bc3330fe`
- base_increment: `1E-8`
- price_increment: `0.01`
- quote_increment: `0.01`
- min_order_quote: `1`
- available_base_after_reservations: `0.0001297967431275`
- reserved_base_open_exit_orders: `0`
- open_exit_orders_count: `0`
- duplicate/oversell: `false/false`
- min-size/min-quote: green

Post-block state:
- local position status: `open`
- open D.3 exit count: `0`
- reservation: `0`
- new D.3 client_order_id: ``
- new D.3 exchange_order_id: ``
- local order status: no new order
- auditstatus: `ok_observe_only`
- journal summary: no immediate `Traceback`, no duplicate/oversell runtime error, service remains active/running

P0/P1/P2/P3:
- P0: geen live action, geen tweede SELL, geen retry storm
- P1: submit v2 geblokkeerd; fingerprint moet opnieuw read-only worden gevalideerd en expliciet geaccepteerd
- P2: sandbox DNS blijft bekend; host-side live product-rules preview werkte
- P3: D.4/D.5/follower later

Next product step:
- `Targeted D.3 Live-Rule Fingerprint Revalidation v2`
- geen live submit voordat de nieuwe fingerprint expliciet is geaccepteerd

## 25. Targeted D.3 Live-Rule Fingerprint Revalidation v2

Timestamp:
- `2026-05-28T16:31:08Z`

Outcome:
- local sanity: green
- service freshness: active/running, PID `881456`, WorkingDirectory `/root/apps/Crypto/coinbase_bot`
- live-rule preview-only check succeeded host-side
- live submit uitgevoerd: `nee`
- Coinbase submit attempted: `false`
- state_write_performed: `false`

Fingerprint result:
- old accepted broad D.2 plan fingerprint:
  - `d1d483d1a64e9e110296781a6f8228aa89260346b949162543a391cf80f1c8dd`
- observed broad D.2 plan fingerprint:
  - `03369854182ca611df0c9a016c1d6208b27707c238976bd90fd2f8701c8dbba4`
- final accepted D.3 candidate fingerprint:
  - `ff33c7ff95b1306b0c05d77f540e7ccca8f18c45d464998ffd5d90b27e3ab9c8`
- fingerprint version:
  - `d3_live_rule_candidate_fingerprint_v1`

Root cause:
- the previous required fingerprint policy was too broad for one-shot D.3 approval because it used the legacy D.2 plan fingerprint.
- the legacy D.2 plan fingerprint includes broad plan/entry fields including mutable position `quote_size`/quote-notional.
- the visible D.3 TP1 candidate and safety fields did not materially change.

Stable D.3 candidate hash fields:
- `ticker`, `position_id`, `side`, `label`, `execution_action`
- `size_base`, `limit_price`, `estimated_quote_value`
- `post_only`, `reduce_only_local`
- `available_base_after_reservations`, `reserved_base_open_exit_orders`, `open_exit_orders_count`
- `base_increment`, `price_increment`, `quote_increment`, `min_order_quote`
- `schema_version`

Excluded from D.3 candidate fingerprint:
- timestamps, generated ids, `client_order_id`, `intent_id`, `plan_id`, `source_plan_id`
- warnings/blockers/fetch errors
- raw product payload ordering
- mutable `position_size_quote` / D.2 `quote_size`

Accepted live-rule candidate:
- side: `SELL`
- label: `TP1`
- execution_action: `place_limit_sell`
- size_base: `0.00006489`
- limit_price: `84800.00`
- estimated_quote_value: `5.5026720000`
- post_only: `true`
- reduce_only_local: `true`
- position_id: `76310097-849e-481c-b587-ba44bc3330fe`
- base_increment: `1E-8`
- price_increment: `0.01`
- quote_increment: `0.01`
- min_order_quote: `1`
- available_base_after_reservations: `0.0001297967431275`
- reserved_base_open_exit_orders: `0`
- open_exit_orders_count: `0`
- duplicate/oversell: `false/false`
- min-size/min-quote: green

Patch:
- `bot/phase_d3_controlled_exit_pilot.py` now reports `selected_candidate_fingerprint`, canonical hash input, hash fields, excluded fields and fingerprint version.
- required-fingerprint guard accepts the stable D.3 candidate fingerprint while retaining legacy D.2 plan fingerprint compatibility for existing tests/audit.
- tests added for nonsemantic quote-notional drift and semantic size/price/position/side/label/action changes.

Validation:
- py_compile: passed
- targeted pytest: `56 passed, 1 warning`
- warning: pytest cache write warning only; no product behavior impact.

Post-run state:
- local position status: `open`
- open D.3 exit count: `0`
- reservation: `0`
- live_submission_attempted/live_order_submitted: `false/false`
- auditstatus: `ok_observe_only`

P0/P1/P2/P3:
- P0: geen duplicate/oversell; geen retry storm; geen live submit uitgevoerd
- P1: stable D.3 candidate fingerprint accepted; Submit v3 requires separate explicit approval
- P2: sandbox DNS blijft bekend; host-side live product-rules preview werkte; monitor-only audit warning remains
- P3: D.4/D.5/follower later

Next product step:
- `Controlled D.3 New Exit Submit v3`
- use accepted candidate fingerprint `ff33c7ff95b1306b0c05d77f540e7ccca8f18c45d464998ffd5d90b27e3ab9c8`
- aparte approval vereist vóór live submit

## 26. Controlled D.3 New Exit Submit v3

Timestamp:
- `2026-05-28T16:37:20Z`

Outcome:
- pre-submit local sanity: green
- service freshness: active/running, PID `881456`, WorkingDirectory `/root/apps/Crypto/coinbase_bot`
- accepted candidate fingerprint matched
- live submit uitgevoerd: `ja`
- exact one submit attempt: `ja`
- Coinbase submit success: `ja`
- state_write_performed: `true`, via existing D.3 submit path only
- no retry
- no lifecycle apply

Approvals used:
- `I_APPROVE_CONTROLLED_D3_NEW_EXIT_SUBMIT_FOR_OPEN_BTC_POSITION`
- `I_UNDERSTAND_THIS_ARMS_ONE_BTC_USDC_TP1_REDUCE_ONLY_LIVE_SELL_ONLY`
- `I_UNDERSTAND_AND_APPROVE_D3_CONTROLLED_REDUCE_ONLY_LIVE_EXITS`

Pre-submit gates:
- local position status: `open`
- position_size_base: `0.0001297967431275`
- bot_managed_base: `0.0001297967431275`
- reserved_base_open_exit_orders before: `0`
- open D.3 exit count before: `0`
- D.3 open-exit position guard: `guard_no_open_d3_exit`
- duplicate/oversell before: `false/false`
- auditstatus before: `ok_observe_only`

Accepted fingerprint check:
- required D.3 candidate fingerprint:
  - `ff33c7ff95b1306b0c05d77f540e7ccca8f18c45d464998ffd5d90b27e3ab9c8`
- observed selected_candidate_fingerprint:
  - `ff33c7ff95b1306b0c05d77f540e7ccca8f18c45d464998ffd5d90b27e3ab9c8`
- version: `d3_live_rule_candidate_fingerprint_v1`
- preview status: `d3_controlled_exit_ready_no_submit`
- preview blockers: `[]`

Submitted D.3 TP1 SELL:
- ticker: `BTC-USDC`
- client_order_id: `phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000`
- exchange_order_id/order_id: `daa5ef77-9967-4fb0-b0c7-4f7c0680b512`
- linked_position_id: `76310097-849e-481c-b587-ba44bc3330fe`
- side: `SELL`
- label: `TP1`
- execution_action: `place_limit_sell`
- size_base: `0.00006489`
- limit_price: `84800.00`
- estimated_quote_value: `5.5026720000`
- post_only: `true`
- reduce_only_local: `true`
- local order status: `submitted`

Post-submit state:
- open D.3 exit count after: `1`
- reserved_base_open_exit_orders after: `0.00006489`
- available_base_after_reservations after: `0.0000649067431275`
- available_plus_reserved_base: `0.0001297967431275`
- local position status: `open`
- duplicate/oversell after: `false/false`
- D.3 readiness now blocks any additional TP1 submit with:
  - `duplicate_exit_label_already_open_for_position`
  - `duplicate_open_exit_order_for_position_action`
- auditstatus: `ok_observe_only`
- service remains active/running

Journal/log summary:
- no immediate `Traceback`
- no immediate `ERROR`
- no duplicate/oversell runtime crash
- service logs continue to show risk-override close decisions skipped by existing governance, not executed

Changed files/state/logs:
- `state/open_orders.json` updated with one new D.3 submitted SELL
- D.3 order/audit logs updated by existing submit path
- `docs/CODEX_PROJECT_CONTEXT.md`
- `docs/D3_OPEN_EXIT_OPERATOR_RUNBOOK.md`
- no `.env` mutation
- no service restart
- no D.3 lifecycle apply

P0/P1/P2/P3:
- P0: geen duplicate/oversell; geen retry storm; geen tweede SELL; further submit is blocked by open TP1 guards
- P1: new live D.3 exit is open/submitted and must be monitored
- P2: sandbox DNS blijft bekend; monitor-only audit warnings remain
- P3: D.4/D.5/follower later

Next product step:
- `Controlled D.3 New Exit Monitor v1`
- monitor Coinbase evidence for `daa5ef77-9967-4fb0-b0c7-4f7c0680b512`
- no lifecycle apply/cancel/replace/second SELL without separate approval

## 27. Controlled D.3 New Exit Monitor v1

Timestamp:
- `2026-05-28T16:41:58Z`

Monitored order:
- ticker: `BTC-USDC`
- client_order_id: `phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000`
- exchange_order_id/order_id: `daa5ef77-9967-4fb0-b0c7-4f7c0680b512`
- linked_position_id: `76310097-849e-481c-b587-ba44bc3330fe`

Outcome:
- local sanity: green
- service freshness: active/running, PID `881456`, WorkingDirectory `/root/apps/Crypto/coinbase_bot`
- read-only Coinbase poll uitgevoerd: `ja`, exact one poll
- live action uitgevoerd: `nee`
- state_write_performed: `false`
- no submit/cancel/replace
- no lifecycle apply

Local sanity:
- local position status: `open`
- local order status: `submitted`
- open D.3 exit count: `1`
- reserved_base_open_exit_orders: `0.00006489`
- available_base_after_reservations: `0.0000649067431275`
- available_plus_reserved_base: `0.0001297967431275`
- D.3 open-exit position guard: `guard_blocked_open_d3_exit_reservation`
- duplicate/oversell: `false/false`

Coinbase evidence:
- coinbase_call_attempted: `true`
- coinbase_call_succeeded: `true`
- lookup attempted:
  - `get_order_by_exchange_order_id`
  - `list_fills_by_exchange_order_id`
- lookup succeeded method: `get_order_by_exchange_order_id`
- raw_status: `OPEN`
- normalized_status: `open`
- filled_base: `0`
- filled_quote: `0`
- avg_fill_price: `0`
- fill_count: `0`
- remaining_size: `0.00006489`
- fees: `0`
- evidence_hash: `9558768e7c0ec66c6ccd7f3d9a5258f17fc18bb5b8d68efcbf465b5f42e07dfe`
- evidence_source: `coinbase_order_snapshot`
- evidence_timestamp: `2026-05-28T16:41:49.798854+00:00`
- proposed_action: `keep_open`
- blockers: `[]`
- warnings: `[]`

Branch:
- `OPEN/open keep_open`
- no fills
- order remains locally `submitted`
- reservation remains intact
- no lifecycle apply in this round

Post-monitor sanity:
- local state unchanged
- open D.3 exit count remains `1`
- reservation remains `0.00006489`
- position remains `open`
- duplicate/oversell remains `false/false`
- auditstatus: `ok_observe_only`
- expected audit warning: `open_d3_exit_orders:1`

P0/P1/P2/P3:
- P0: no duplicate/oversell; no second SELL; no unauthorized apply; no live action
- P1: D.3 TP1 exit is still `OPEN/open`; monitoring continues
- P2: sandbox DNS blijft bekend; monitor-only warnings remain expected
- P3: D.4/D.5/follower later

Next product step:
- `Controlled D.3 New Exit Monitor v2` later, or read-only lifecycle evidence poll after agreed interval/market event
- no lifecycle apply/cancel/replace/second SELL without separate approval

## 28. Controlled D.3 New Exit Monitor v2

Timestamp:
- `2026-05-28T16:59:34Z`

Monitored order:
- ticker: `BTC-USDC`
- client_order_id: `phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000`
- exchange_order_id/order_id: `daa5ef77-9967-4fb0-b0c7-4f7c0680b512`
- linked_position_id: `76310097-849e-481c-b587-ba44bc3330fe`

Outcome:
- local sanity: green
- service freshness: active/running, PID `881456`, WorkingDirectory `/root/apps/Crypto/coinbase_bot`
- read-only Coinbase poll uitgevoerd: `ja`, exact one poll
- live action uitgevoerd: `nee`
- state_write_performed: `false`
- no submit/cancel/replace
- no lifecycle apply

Local sanity:
- local position status: `open`
- local order status: `submitted`
- open D.3 exit count: `1`
- reserved_base_open_exit_orders: `0.00006489`
- available_base_after_reservations: `0.0000649067431275`
- available_plus_reserved_base: `0.0001297967431275`
- D.3 open-exit position guard: `guard_blocked_open_d3_exit_reservation`
- duplicate/oversell: `false/false`

Coinbase evidence:
- coinbase_call_attempted: `true`
- coinbase_call_succeeded: `true`
- lookup attempted:
  - `get_order_by_exchange_order_id`
  - `list_fills_by_exchange_order_id`
- lookup succeeded method: `get_order_by_exchange_order_id`
- raw_status: `OPEN`
- normalized_status: `open`
- filled_base: `0`
- filled_quote: `0`
- avg_fill_price: `0`
- fill_count: `0`
- remaining_size: `0.00006489`
- fees: `0`
- evidence_hash: `9558768e7c0ec66c6ccd7f3d9a5258f17fc18bb5b8d68efcbf465b5f42e07dfe`
- evidence_source: `coinbase_order_snapshot`
- evidence_timestamp: `2026-05-28T16:59:24.887584+00:00`
- proposed_action: `keep_open`
- blockers: `[]`
- warnings: `[]`

Branch:
- `OPEN/open keep_open`
- no fills
- order remains locally `submitted`
- reservation remains intact
- no lifecycle apply in this round

Post-monitor sanity:
- local state unchanged
- open D.3 exit count remains `1`
- reservation remains `0.00006489`
- position remains `open`
- duplicate/oversell remains `false/false`
- auditstatus: `ok_observe_only`
- expected audit warning: `open_d3_exit_orders:1`

P0/P1/P2/P3:
- P0: no duplicate/oversell; no second SELL; no unauthorized apply; no live action
- P1: D.3 TP1 exit is still `OPEN/open`; monitoring continues
- P2: sandbox DNS blijft bekend; monitor-only warnings remain expected
- P3: D.4/D.5/follower later

Next product step:
- `Controlled D.3 New Exit Monitor v3` later, or read-only lifecycle evidence poll after agreed interval/market event
- no lifecycle apply/cancel/replace/second SELL without separate approval

## 29. Controlled D.3 Exit Monitoring Policy & Next-Step Planner v1

Timestamp:
- `2026-05-28T19:25:14Z`

Monitored order:
- ticker: `BTC-USDC`
- client_order_id: `phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000`
- exchange_order_id/order_id: `daa5ef77-9967-4fb0-b0c7-4f7c0680b512`
- linked_position_id: `76310097-849e-481c-b587-ba44bc3330fe`
- side: `SELL`
- limit_price: `84800.00`
- size_base / remaining_size: `0.00006489`
- post_only: `true`
- reduce_only_local: `true`

Local sanity:
- status: `green`
- local position status: `open`
- local order status: `submitted`
- open D.3 exit count: `1`
- reserved_base_open_exit_orders: `0.00006489`
- available_base_after_reservations: `0.0000649067431275`
- available_plus_reserved_base: `0.0001297967431275`
- D.3 open-exit position guard: `guard_blocked_open_d3_exit_reservation`
- duplicate/oversell: `false/false`

Service freshness:
- service status: `active/running`
- service PID: `881456`
- ExecMainStartTimestamp: `Thu 2026-05-28 14:39:18 UTC`
- WorkingDirectory: `/root/apps/Crypto/coinbase_bot`
- no service restart performed

Trigger evaluation:
- last successful poll timestamp: `2026-05-28T16:59:24.887584+00:00`
- time trigger: `true`, more than 30-60 minutes elapsed
- market trigger: `not required for decision`; no orderbook action performed
- lifecycle trigger: `false` before poll
- safety trigger: `false`
- operator trigger: `false` for immediate live action
- trigger_present: `yes`
- trigger_reason: `time_elapsed_since_last_successful_poll`

Read-only Coinbase poll:
- poll executed: `yes`, exactly one successful poll after the time trigger
- sandbox DNS failed first; repeated once with network access
- coinbase_call_attempted: `true`
- coinbase_call_succeeded: `true`
- lookup attempted: `get_order_by_exchange_order_id`, `list_fills_by_exchange_order_id`
- lookup succeeded method: `get_order_by_exchange_order_id`
- raw_status: `OPEN`
- normalized_status: `open`
- filled_base: `0`
- filled_quote: `0`
- avg_fill_price: `0`
- fill_count: `0`
- remaining_size: `0.00006489`
- fees: `0`
- evidence_hash: `9558768e7c0ec66c6ccd7f3d9a5258f17fc18bb5b8d68efcbf465b5f42e07dfe`
- evidence_source: `coinbase_order_snapshot`
- evidence_timestamp: `2026-05-28T19:25:03.991177+00:00`
- proposed_action: `keep_open`
- blockers: `[]`
- warnings: `[]`

Branch:
- `OPEN/open keep_open`
- no fills
- order remains locally `submitted`
- reservation remains intact
- no lifecycle apply in this round

Execution/write status:
- live action: `no`
- state_write_performed: `false`, except docs
- no Coinbase submit/cancel/replace
- no D.3 lifecycle apply
- no retry storm

Post-monitor sanity:
- local state unchanged
- open D.3 exit count remains `1`
- reservation remains `0.00006489`
- position remains `open`
- duplicate/oversell remains `false/false`
- auditstatus: `ok_observe_only`
- expected audit warning: `open_d3_exit_orders:1`

P0/P1/P2/P3:
- P0: no duplicate/oversell; no second SELL; no unauthorized apply; no live action
- P1: D.3 TP1 exit is still `OPEN/open`; `keep_open` remains correct
- P2: sandbox DNS can block local poll attempts; no retry storm
- P3: D.4/D.5/follower/replication remain later

Planning advice:
- Do not prompt-monitor again without a trigger.
- Next lifecycle poll only after 30-60 minutes, a market move near `84800.00`, lifecycle evidence, local safety drift, or explicit operator request.
- Bij `OPEN/open`: `keep_open`, geen state write, geen live actie.
- Bij `PARTIAL`/`FILLED`: stop voor `Controlled D.3 Lifecycle Apply on Fill Evidence v1` met aparte ACK.
- Bij `CANCELLED`/`EXPIRED`/`REJECTED`: stop voor `Controlled D.3 Terminal Closeout Reconcile v1` met aparte ACK.
- D.4 trailing/cancel-replace pas na bewezen stabiele lifecycle apply/terminal closeout-route.

Next product step:
- Wait for interval, market event, lifecycle evidence or safety drift before the next `Controlled D.3 New Exit Monitor`.

## 30. Controlled D.3 Exit Price Review / Reprice Decision v1

Timestamp:
- `2026-05-28T19:33:59Z`

Active order:
- ticker: `BTC-USDC`
- client_order_id: `phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000`
- exchange_order_id/order_id: `daa5ef77-9967-4fb0-b0c7-4f7c0680b512`
- linked_position_id: `76310097-849e-481c-b587-ba44bc3330fe`
- side: `SELL`
- label: `TP1`
- local status: `submitted`
- Coinbase status: `OPEN/open`
- size_base / remaining_size: `0.00006489`
- limit_price: `84800.00`
- post_only: `true`
- reduce_only_local: `true`
- filled_base: `0`
- fill_count: `0`

Local sanity:
- status: `green`
- local position status: `open`
- local order status: `submitted`
- open D.3 exit count: `1`
- reserved_base_open_exit_orders: `0.00006489`
- available_base_after_reservations: `0.0000649067431275`
- available_plus_reserved_base: `0.0001297967431275`
- D.3 open-exit position guard: `guard_blocked_open_d3_exit_reservation`
- duplicate/oversell: `false/false`

Service freshness:
- service status: `active/running`
- service PID: `881456`
- ExecMainStartTimestamp: `Thu 2026-05-28 14:39:18 UTC`
- WorkingDirectory: `/root/apps/Crypto/coinbase_bot`
- no service restart performed

Coinbase order status:
- read-only lifecycle poll executed: `yes`, exactly one
- raw_status: `OPEN`
- normalized_status: `open`
- filled_base: `0`
- filled_quote: `0`
- avg_fill_price: `0`
- fill_count: `0`
- remaining_size: `0.00006489`
- evidence_hash: `9558768e7c0ec66c6ccd7f3d9a5258f17fc18bb5b8d68efcbf465b5f42e07dfe`
- evidence_timestamp: `2026-05-28T19:32:09.153651+00:00`
- proposed_action: `keep_open`
- no state write
- no live action

Current market data:
- orderbook best_bid/best_ask at `2026-05-28T19:32:30.422490Z`: `73440.63` / `73440.64`
- public ticker best_bid/best_ask near `2026-05-28T19:33:22Z`: `73412.26` / `73412.27`
- analysis mid_price: `73412.265`
- last/current price: `73412.27`
- spread: `0.01`
- product rules:
  - base_increment: `0.00000001`
  - price_increment: `0.01`
  - quote_increment: `0.01`
  - min_order_quote: `1`
  - min_order_base: `0.00000001`

Price distance:
- current_exit_price: `84800.00`
- distance_to_bid_pct: `15.51204117677347080719215019`
- distance_to_ask_pct: `15.51202544206847166011894197`
- distance_to_mid_pct: `15.51203330942043539999753447`
- expected_quote_current_order: `5.5026720000`
- estimated_quote_at_bid: `4.7637215514`
- estimated_quote_at_ask: `4.7637222003`
- estimated_quote_at_mid: `4.76372187585`
- classification: `TP1 far above market`
- fill_probability_short_term: `low`

D.2/D.3 plan reference:
- D.2 status: `position_executor_plan_ready_no_live_exit_submit`
- D.2 entry_price: `80000`
- D.2 TP1 target: `84800.000`
- D.2 fee model estimated total cost pct: `0.0125`
- D.2 minimum expected net edge pct: `0.0125`
- current TP1 approximate net edge: `+4.7500%`
- near-market ask approximate net edge: `-9.484662500%`
- fee-aware minimum target estimate: `82000.00`
- breakeven-cost estimate: `81000.00`

Reprice options:
- Option 1, keep current TP1:
  - price: `84800.00`
  - estimated_quote: `5.5026720000`
  - likely fill probability: low short term
  - comment: preserves original D.2 TP1 and profit target
- Option 2, conservative near-market maker reprice:
  - price: `73412.28` (`best_ask + 1 tick`)
  - estimated_quote: `4.7637228492`
  - likely fill probability: higher
  - comment: loss/de-risk exit, not TP1; must be rechecked immediately before submit to stay post-only
- Option 3, plan-based fee-aware reprice:
  - price: `82000.00`
  - estimated_quote: `5.320980000000`
  - likely fill probability: still low short term, but less far than `84800.00`
  - comment: preserves approximate minimum net edge; still requires cancel-first replace approval

Decision branch:
- decision: `reprice_recommended_awaiting_approval`
- reason: current TP1 is technically safe but too far above market for short-term fill
- recommended framing: choose explicitly between a faster loss/de-risk reprice near ask and a plan-preserving fee-aware target near `82000.00`
- no cancel performed
- no replace performed
- no submit performed
- no lifecycle apply performed

Post-check:
- live action: `no`
- state_write_performed: `false`, except docs
- open D.3 exit count remains `1`
- reservation remains `0.00006489`
- duplicate/oversell remains `false/false`
- auditstatus: `ok_observe_only`
- expected audit warning: `open_d3_exit_orders:1`

P0/P1/P2/P3:
- P0: local/live safety remains coherent
- P1: price review shows TP1 is a far swing target, not a near-fill order
- P2: any replacement must be cancel-first with exact price approval
- P3: no D.4 automation or learning in this branch

Next product step:
- `Controlled D.3 Exit Cancel/Replace Reprice v1` with separate approval and exact replacement price, or keep current TP1 as higher swing target.

## Checkpoint: Controlled D.3 Exit Cancel/Replace Reprice Decision v1

Timestamp: `2026-05-28T20:50:40Z`

Local sanity:
- position status: `open`
- active local order status: `submitted`
- open D.3 exit count: `1`
- reservation: `0.00006489`
- duplicate/oversell: `false/false`
- service status: `coinbase-bot active/running`

Coinbase order status:
- read-only poll result: `OPEN/open`
- proposed_action: `keep_open`
- filled_base: `0`
- filled_quote: `0`
- fill_count: `0`
- remaining_size: `0.00006489`
- evidence_timestamp: `2026-05-28T20:50:20.372122+00:00`

Market data:
- best_bid: `73572.59`
- best_ask: `73572.60`
- mid_price: `73572.595`
- spread: `0.01`
- price_increment: `0.01`
- min_order_quote: `1`

Selected option A/B/C:
- selected option: `none`
- approval present: `no`
- reason: no explicit choice ACK and no one-shot cancel/replace ACK were present

Replacement candidate:
- A keep current:
  - price: `84800.00`
  - size_base: `0.00006489`
  - estimated_quote: `5.5026720000`
  - label: `keep_current_exit`
- B near-market de-risk:
  - price: `73572.61` (`best_ask + 1 tick`)
  - size_base: `0.00006489`
  - estimated_quote: `4.7741266629`
  - label: `reprice_near_market_derisk`
  - note: faster-fill/loss-de-risk candidate, below D.2 entry and fee-aware breakeven
- C plan-preserving:
  - price: `82000.00`
  - size_base: `0.00006489`
  - estimated_quote: `5.3209800000`
  - label: `reprice_plan_preserving`

Execution:
- live action executed: `no`
- cancel attempted/succeeded: `no/no`
- replace attempted/succeeded: `no/no`
- lifecycle apply: `no`
- D.4 automation: `no`
- state write: `false`, except docs

Post-check:
- open D.3 exit count: `1`
- reservation: `0.00006489`
- position status: `open`
- duplicate/oversell: `false/false`
- auditstatus: `ok_observe_only`

Next product step:
- Provide exactly one of:
  - `I_CHOOSE_KEEP_CURRENT_D3_TP1_84800_NO_REPRICE`
  - `I_APPROVE_D3_CANCEL_REPLACE_REPRICE_TO_82000_PLAN_PRESERVING`
  - `I_APPROVE_D3_CANCEL_REPLACE_REPRICE_TO_NEAR_MARKET_DERISK_LOSS_ACCEPTED`
- For any live cancel/replace, also provide:
  - `I_UNDERSTAND_AND_APPROVE_D3_CANCEL_REPLACE_REPRICE_ONE_SHOT`

## Checkpoint: Controlled D.3 Exit Price Review / Reprice Decision v1

Timestamp: `2026-05-28T20:42:46Z`

Active order details:
- `ticker=BTC-USDC`
- `client_order_id=phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000`
- `exchange_order_id=daa5ef77-9967-4fb0-b0c7-4f7c0680b512`
- `linked_position_id=76310097-849e-481c-b587-ba44bc3330fe`
- `side=SELL`, `label=TP1`
- `size_base=0.00006489`
- `remaining_size=0.00006489`
- `limit_price=84800.00`
- `post_only=true`
- `reduce_only_local=true`

Local sanity:
- position status: `open`
- position_size_base: `0.0000649067431275`
- bot_managed_base: `0.0001297967431275`
- reserved_base_open_exit_orders: `0.00006489`
- available_base_after_reservations: `0.0000649067431275`
- open D.3 exit count: `1`
- duplicate/oversell: `false/false`

Service freshness:
- service: `coinbase-bot`
- status: `active/running`
- PID: `881456`
- started: `Thu 2026-05-28 14:39:18 UTC`
- working directory: `/root/apps/Crypto/coinbase_bot`

Coinbase order status:
- read-only poll: `OPEN/open`
- proposed_action: `keep_open`
- filled_base: `0`
- filled_quote: `0`
- avg_fill_price: `0`
- fill_count: `0`
- evidence_hash: `9558768e7c0ec66c6ccd7f3d9a5258f17fc18bb5b8d68efcbf465b5f42e07dfe`
- evidence_timestamp: `2026-05-28T20:41:43.555170+00:00`
- no cancel, no replace, no submit, no lifecycle apply

Current market data:
- best_bid: `73566.39`
- best_ask: `73566.40`
- mid_price: `73566.395`
- spread: `0.01`
- current/mark reference: `73566.395`
- product rules:
  - base_increment: `0.00000001`
  - price_increment: `0.01`
  - quote_increment: `0.01`
  - min_order_quote: `1`
  - min_order_base: `0.00000001`

Price distance:
- current_exit_price: `84800.00`
- distance_to_bid_pct: `15.27003024071182506032985987`
- distance_to_ask_pct: `15.27001457186976663259314035`
- distance_to_mid_pct: `15.27002240629026337365042830`
- expected_quote_current_order: `5.5026720000`
- current estimated quote at bid: `4.7737230471`
- current estimated quote at ask: `4.7737236960`
- current estimated quote at mid: `4.77372337155`
- classification: `TP1 far above market`
- fill probability assessment: low short term

D.2/D.3 plan reference:
- D.2 status: `position_executor_plan_ready_no_live_exit_submit`
- D.2 plan_id: `d2-BTC-USDC-20260528204215`
- D.2 plan fingerprint: `ba224d9cc75765b2333ef457cec23c0064d5f977c1027e36a244983505bdda62`
- D.2 entry_price: `80000`
- D.2 TP1 target: `84800.000`
- D.2 TP2 target: `85648.0000000`
- fee model total cost pct: `0.0125`
- minimum expected net edge pct: `0.0125`
- current TP1 approximate net edge: `+4.7500%`
- near-market ask is below D.2 entry and below fee-aware breakeven
- fee-cost breakeven estimate: `81000.00`
- fee-aware minimum net-edge target estimate: `82000.00`

Reprice options:
- Option 1, keep current TP1:
  - price: `84800.00`
  - size_base: `0.00006489`
  - estimated_quote: `5.5026720000`
  - likely fill probability: low short term
  - comment: preserves D.2 TP1 profit target
- Option 2, conservative near-market maker reprice:
  - price: `73566.41` (`best_ask + 1 tick`)
  - size_base: `0.00006489`
  - estimated_quote: `4.7737243449`
  - likely fill probability: higher than current TP1
  - post_only safety: must be rechecked immediately before submit
  - comment: de-risk/loss exit, not TP1
- Option 3, plan-based fee-aware reprice:
  - price: `82000.00`
  - size_base: `0.00006489`
  - estimated_quote: `5.320980000000`
  - likely fill probability: still low short term, but better than `84800.00`
  - post_only safety: above current market while BTC-USDC remains near `73566`
  - comment: preserves approximate minimum D.2 net edge

Decision branch:
- decision: `reprice_recommended_awaiting_approval`
- reason: `84800.00` is coherent as TP1 but too far above current market for short-term fill
- recommended framing: choose explicitly between keeping the swing TP1, a near-ask loss/de-risk maker exit, or a plan-preserving fee-aware reprice around `82000.00`
- next product step: `Controlled D.3 Exit Cancel/Replace Reprice v1`
- required approvals later: cancel old order, exact replacement price, replacement order submit, no retry storm

Post-check:
- live action: `no`
- state_write_performed: `false`, except docs
- open D.3 exit count: `1`
- reservation remains: `0.00006489`
- duplicate/oversell: `false/false`
- auditstatus: `ok_observe_only`

P0/P1/P2/P3:
- P0: local/live safety coherent
- P1: TP1 price is far above market
- P2: replacement path must be cancel-first and ACK-gated
- P3: no D.4 automation, learning, follower/replication

Next product step:
- `Controlled D.3 Exit Cancel/Replace Reprice v1` with separate approval and exact replacement price, or keep current TP1 as higher swing target.
