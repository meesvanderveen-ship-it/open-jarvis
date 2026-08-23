# Coinbase bot architecture and functions

> **STALE OPERATIONAL-STATE WARNING — 2026-06-19**
>
> Any statement below describing an open BTC-USDC D3 order is historical and
> must not be used as live evidence. Current read-only local state instead
> records an open ADA-USDC position with pending D2/D3. No local repair or
> Coinbase action is authorized by this warning.

## 1. Executive summary

Dit project is een Coinbase spot LLM tradingbot. De bot is spot-only, gebruikt een multi-agent analyseketen, zet daar een deterministische risk/safety-laag achter en laat live execution alleen via expliciet gegate paden toe.

De huidige live-operatie zit in D.3 open-exit lifecycle governance. Er staat momenteel exact één open TP1 SELL voor `BTC-USDC`. Zolang die lifecycle open blijft, mogen geen nieuwe live acties ontstaan vanuit entry, exit, retry, cancel, replace of apply-branches zonder een aparte expliciete operationele beslissing.

## 2. Current operational state

- Huidige actieve lifecycle: D.3 controlled live exit, open TP1 lifecycle.
- Huidige open D.3 TP1 SELL:
  - `ticker=BTC-USDC`
  - `client_order_id=phased3-BTCUSDC-TP1-bc3330fe-6T0949383258870000`
  - `exchange_order_id=bb13e1e1-9e6e-4b2c-b446-87eaa5f52f31`
  - `linked_position_id=76310097-849e-481c-b587-ba44bc3330fe`
  - `side=SELL`
  - `exit_label=TP1`
  - `limit_price=81664.97`
  - `remaining_size=0.00006489`
- Status volgens laatste checkpoint:
  - `raw_status=OPEN`
  - `normalized_status=open`
  - `filled_base=0`
  - `filled_quote=0`
  - `fill_count=0`
  - `suggested_local_action=keep_open`
  - geen cancel-candidate
  - geen replace-candidate
- Huidige freeze/safetyregels:
  - geen live BUY
  - geen tweede SELL
  - geen retry
  - geen cancel
  - geen replace
  - geen reconcile apply
  - geen recovery apply
  - geen service restart
  - geen `.env`-mutatie
  - geen state mutation bij `OPEN/open`

## 3. High-level bot flow

De totale keten is:

market data / feature pack  
-> gatekeeper  
-> pending intents / watchlist  
-> specialist analysts  
-> bull/bear debate  
-> synthesizer  
-> final judge  
-> deterministic risk layer  
-> trade plan / execution intent  
-> C.4.3 live entry bridge  
-> Coinbase post-only BUY  
-> order store  
-> lifecycle reconciliation  
-> fill-to-position  
-> D.2 position executor plan  
-> D.3 exit preview / controlled live exit  
-> D.4 dynamic cancel/replace/trailing later  
-> D.5 execution learning later

Belangrijke architectuurregel: de AI-keten mag ideeën genereren, maar pas de deterministische laag en de expliciete live-gates bepalen of iets paper-only blijft, preview-only blijft of werkelijk naar Coinbase mag.

## 4. AI and agent layers

### 4.1 Market data / feature pack

De bot bouwt per ticker een `feature_pack` als input voor de AI-keten. Die context bevat onder meer:

- tickers en actuele market context
- OHLCV / indicatorblokken
- regime- en structuurcontext
- EMA, ADX, RSI, Bollinger Bands, Donchian en aanverwante indicatoren
- microstructure / orderbook context
- risk context / engine state
- headlines / news sentiment / bredere context indien beschikbaar

`feature_pack` is de gedeelde feitelijke basis voor gatekeeping, analysts, planner, judge en risk checks.

### 4.2 Gatekeeper

De gatekeeper is de vroege goedkope filterlaag. In `StrategyEngine` draait eerst een entry gate / prefilter om tickers te classificeren als grofweg reject, wait/watch of allow for deeper review.

Doelen:

- vroeg filteren
- spot-only constraints handhaven
- dure LLM-routes beperken
- pending plans/intents kunnen promoveren naar fresh analysis, maar nooit rechtstreeks naar execution

De gatekeeper mag een setup terugsturen naar watch/pending-context, maar execution-permission ontstaat hier nooit.

### 4.3 Specialist analysts

Na gatekeeping volgt de specialistische analyseketen:

- trend specialist
- breakout specialist
- mean-reversion specialist
- regime/context specialist
- bull debater
- bear debater
- synthesizer

De code in `strategy_engine.py` en `prompts.py` laat zien dat deze modules elk een afgebakende JSON-output hebben. De bull/bear-laag maakt expliciet een argumentatieve spanning zichtbaar. De synthesizer combineert dat tot één thesis met onder meer `setup_type`, `composite_confidence`, `primary_thesis`, `why_now`, `key_trigger` en `invalidation`.

### 4.4 Final judge

De final judge is de laatste AI-beslisser. Hij ontvangt niet alleen de analyst-output, maar ook:

- `feature_pack`
- bestaande positiecontext
- chart-pattern context
- recent reflections
- decision outcomes
- pending trade plan context
- een expliciet `trade_plan` van de trade planner

De judge moet output-clean en JSON-clean zijn. De relevante beslissingen zijn:

- `approve_trade`
- `wait`
- `reject`
- `reduce_size`
- `close_position`

Voor nieuwe entries hoort `approve_trade` alleen bij `side=BUY`. Bij conflicterende signalen is de architectuur bewust conservatief: vaak `wait` of `reject`.

### 4.5 Deterministic risk layer

De bot vertrouwt de LLM nooit blind. In `StrategyEngine._hard_risk_gate(...)` en de omliggende safety-lagen worden harde rails afgedwongen:

- position limits
- max notional
- available balance checks
- minimum size
- cooldown / trading_disabled / cancel_only checks
- duplicate order guards via `OrderStore`
- safety flags uit config
- no short
- no naked sell
- no averaging down in D.2
- bestaande positie vereist voor `reduce_size` / `close_position`

De AI levert dus een voorstel; de deterministische laag beslist of dat voorstel überhaupt uitvoerbaar is.

## 5. Execution architecture

### 5.1 Paper/read-only planning

De normale architectuur is eerst paper/read-only:

- trade plan maken
- execution intent structureren
- pending plan / pending intent eventueel bewaren
- geen live submit zonder expliciete gating

Zelfs trigger-ready pending context betekent alleen: opnieuw analyseren. Nooit: direct handelen.

### 5.2 C.4.3 live BUY-entry

C.4.3 is de gecontroleerde live BUY-entrybrug.

Eigenschappen:

- post-only BUY
- kleine pilot sizing
- `OrderStore` mapping van `client_order_id` en `exchange_order_id`
- reject hardening
- `success=false` of submit reject mag niet als open order blijven hangen
- geen follower lifecycle
- geen live SELL vanuit entry path

`phase_c43_autonomous_entry_live.py` is de entry-only bridge van StrategyEngine naar Coinbase. Deze laag registreert het order lokaal, maar creëert nog geen positie zonder echte fill evidence.

### 5.3 C.4.4 lifecycle / poll / apply governance

C.4.4 regelt lifecycle governance voor C.4.3 live orders.

Kernpunten:

- read-only snapshot eerst
- poll-to-apply closeout wrapper
- `apply_local` is governed
- `OPEN/open` leidt tot `keep_open`
- `CANCELLED` / `EXPIRED` / `REJECTED` kunnen via closeout apply afgehandeld worden
- fill apply vereist expliciete toestemming

`phase_c44_poll_to_apply_closeout.py` previewt altijd eerst. `phase_c43_lifecycle_orchestrator.py` is read-only by default en mag bij apply alleen lokale lifecycle-metadata aanpassen; geen Coinbase submit, cancel of SELL.

### 5.4 C.4.5 live fill pilot

C.4.5 bewijst de overgang van live BUY-order naar echte positie.

Kernpunten:

- maker price scout
- live fill proof
- fill-to-position
- fees / `fill_count` / `avg_fill_price`
- `position_created`
- optioneel D.2 plan en D.3 preview direct na coherente fill apply

`phase_c45_live_fill_pilot.py` dwingt een aparte ACK af voor fill apply. Pas daarna mag de lokale state van open C.4.3 order naar positie worden omgezet.

## 6. Position and exit architecture

### 6.1 D.2 position executor

D.2 bouwt een `position_executor_plan` voor een echte open positie. Het is bracket-lite planning, geen live submitter.

Inhoud van het plan:

- entry / entry_price
- invalidation / stop
- TP1 / TP2
- runner
- trailing activation / trailing distance
- time limit
- fee-aware minimum net edge
- no averaging down
- position / fingerprint coherence
- base / reservation awareness

`phase_d2_position_executor.py` genereert een fingerprint voor het plan, bewaakt fee-edge en zorgt dat TP2 niet onder TP1 uitkomt. D.2 is preview/persist voor planning; D.3 is nodig voor echte live reduce-only exits.

### 6.2 D.3 controlled live exits

D.3 vertaalt een D.2-plan naar een gecontroleerde spot-SELL lifecycle.

Kernpunten:

- preview-only first
- controlled one-shot SELL
- reduce-only semantiek lokaal afgedwongen
- duplicate exit protection
- no oversell

Spot heeft geen native reduce-only, dus D.3 gebruikt reservation-aware lokale invarianten:

- `position_size_base = available/unreserved base`
- `bot_managed_base = available + reserved`
- `reserved_base_open_exit_orders = som van open exit-reservations`

`phase_d3_controlled_live_exits.py` selecteert maximaal één veilig exit-intent per cyclus, normaliseert grootte op product increments, blokkeert trailing live submit nog tot D.4 en dwingt ACK + live flags af voor echte submit.

D.3 reconciliation governance:

- `OPEN` -> `keep_open`
- `PARTIAL` / `FILLED` / `CANCELLED` / `EXPIRED` / `REJECTED` -> eerst dry-run, daarna eventueel apply
- apply vereist expliciete ACK

Huidige actieve live exit:

- één open `TP1` SELL voor `BTC-USDC`

### 6.3 D.3 stale/open governance

Voor open orders bestaat extra governance:

- `stale_open_review`
- `cancel_candidate_preview_only`
- `replace_candidate_preview_only`
- geen atomic cancel+replace
- controlled cancel-only first
- eerst closeout, daarna pas nieuwe preview/fingerprint

Dat voorkomt dat een open SELL-order tegelijk gemuteerd en vervangen wordt terwijl reservation/base-state nog niet coherent is.

## 7. Safety gates and invariants

- central live-exit gate
- legacy SELL-route must stay blocked
- live BUY gate
- live SELL gate
- D.3 actual submit gate
- ACK gates
- no duplicate exits
- no oversell
- no negative base
- no state mutation at `OPEN/open`
- no recovery apply without explicit diagnosis and approval
- no service restart during active lifecycle
- no `.env` mutation
- no secrets printing
- no replication/follower order lifecycle
- unknown Coinbase/network status = fail-closed

Aanvullend:

- `live_exit_gate.py` blokkeert SELL tenzij alle flags én de juiste bron én de juiste ACK aanwezig zijn
- C.4.3 blijft entry-only
- D.3 actual submit is een aparte gate, los van preview
- `OrderStore` bewaakt duplicate entry en duplicate exit situaties

## 8. State, logs, and source-of-truth files

Belangrijke source-of-truth en operatiebestanden:

- `docs/CODEX_PROJECT_CONTEXT.md`
- `docs/D3_OPEN_EXIT_OPERATOR_RUNBOOK.md`
- `docs/COINBASE_BOT_TOTAL_ROADMAP_FROM_D3_OPEN_EXIT.md`
- `docs/COINBASE_BOT_ARCHITECTURE_AND_FUNCTIONS.md`
- `state/open_orders.json`
- `state/positions.json`

Belangrijke logs en auditsporen:

- `logs/order_events.jsonl`
- `logs/live_exit_orders.jsonl`
- `logs/phase_d2_position_executor.jsonl`
- `logs/execution.jsonl`
- `logs/execution_outcomes.jsonl`

Belangrijke read-only operator/tools:

- `tools/show_function_preservation_audit.py`
- `tools/show_phase_c43_autonomous_entry_live.py`
- `tools/show_phase_d3_live_exit_order_snapshot.py`
- `tools/reconcile_phase_d3_live_exit_order.py`
- `tools/show_phase_d3_open_exit_order_governance.py`
- `tools/show_phase_d3_cancel_replace_governance.py`

Deze combinatie vormt samen het operationele beeld: docs voor branchregels, state files voor lokale lifecycle, logs voor audittrail, en read-only tools voor diagnose en preview.

## 9. Replication/follower architecture

Replication/follower bestaat als architectuurspoor, maar mag de master-lifecycle niet overnemen.

- replication publisher bestaat
- follower / replica mag geen master order lifecycle overnemen
- tijdens actieve D.3 lifecycle blijft replication disabled / isolated
- geen follower-triggered BUY
- geen follower-triggered SELL
- geen follower-triggered cancel
- geen follower-triggered replace
- future follower support pas na master lifecycle hardening

De codebase noemt herhaaldelijk `followers_not_in_order_lifecycle` en `replication_disabled` als expliciete safety-claims voor fase C en D.

## 10. Coinbase/network failure handling

Operationeel uitgangspunt:

- sandbox DNS/runtime naar `api.coinbase.com` kan falen
- sandbox failure is geen trading-signaal
- alleen exact dezelfde read-only Coinbase-check buiten sandbox mag herhaald worden
- nooit submit/cancel/replace/apply op basis van netwerkfout
- unknown status = fail-closed

Een netwerkfout mag dus nooit geïnterpreteerd worden als fill, cancel of execution permission.

## 11. What is already proven live

- C.4.3 post-only BUY live proven
- order id mapping fixed
- reject hardening
- C.4.4 poll/apply closeout
- C.4.5 live fill pilot
- fill-to-position
- D.2 plan on real fill
- D.3 preview on real position
- first controlled D.3 TP1 SELL submitted
- current open D.3 lifecycle under keep_open governance

## 12. What is not yet proven / still pending

- D.3 TP1 fill reconciliation apply after actual `FILLED` / `PARTIAL`
- D.3 `CANCELLED` / `EXPIRED` / `REJECTED` closeout apply after real status change
- controlled cancel-only governance pilot
- replace flow after cancel-first
- D.4 dynamic trailing/cancel-replace
- D.5 execution learning
- follower / replica live lifecycle
- cleanup / compression of repeated checkpoints

## 13. Functional gaps to keep in roadmap

- legacy SELL-route audit / central live-exit gate before any future SELL
- replication / follower isolation
- pre-apply state snapshot before every ACK mutation
- partial-fill edgecases:
  - multiple fills
  - fees
  - avg_fill_price
  - dust
  - remaining_size under minimum
  - partial reservation release
- D.2 fingerprint / live-rules revalidation after each lifecycle change
- Coinbase product-rules gate:
  - base increment
  - quote increment
  - min order quote
  - min base size
  - rounded sell_base
  - estimated_quote
- concrete stale/cancel/replace thresholds for D.4
- post-apply sanity checklist
- logging / observability checklist
- secrets / env / ops safety
- D.5 learning-to-execution gate

## 14. Planning implications

Deze architectuur leidt direct tot de operationele planning:

1. huidige open TP1 lifecycle blijft leidend
2. geen nieuwe live action totdat branch wijzigt of candidate ontstaat
3. statuswijziging -> dry-run first
4. apply only with ACK
5. after coherent apply -> D.2/D.3 preview/fingerprint
6. controlled cancel-only before any replace
7. D.4 only after current lifecycle
8. D.5 only after complete exit events

Planning mag dus niet meer alleen uit losse D.3-checkpoints worden afgeleid; ze moet op de volledige architectuur en branch-invarianten steunen.

## 15. Codex usage guidance

- Codex moet altijd eerst docs lezen
- geen aannames op basis van oude memory alleen
- geen Word-documenten gebruiken als serverbron
- geen live tools zonder expliciete opdracht
- bij onzekerheid fail-closed
- bij planningvragen dit architectuurdocument + roadmap gebruiken
- bij actuele D.3 order dit operator-runbook gebruiken

Concreet:

- `docs/CODEX_PROJECT_CONTEXT.md` blijft de primaire source of truth
- `docs/D3_OPEN_EXIT_OPERATOR_RUNBOOK.md` bepaalt de branch van de actuele open D.3 order
- `docs/COINBASE_BOT_TOTAL_ROADMAP_FROM_D3_OPEN_EXIT.md` bepaalt welke vervolgstappen logisch en toegestaan zijn
- dit document legt de functionele totaalkaart vast waarop toekomstige planning moet steunen
