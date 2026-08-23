# AGENTS.md - Coinbase Spot LLM Tradingbot

## Projectdoel

Dit repo draait een Coinbase spot LLM tradingbot met autonome analyse, live orderbook BUY entries, D.2 position planning, D.3 controlled limit SELL exits, learning/prelearning sidecar en bounded live testing. Codex werkt safety-first en productgericht: voer de volgende veilige productstap uit wanneer die duidelijk is, maar stop bij approval gates, safety-failures of lifecycle-evidence die een aparte ACK vereist.

## Huidige Modes

- Mode A: autonomous analysis + orderbook BUY + D3 limit SELL + D3 lifecycle polling + controlled stop-exit preview-only.
- Mode B: Mode A + controlled autonomous stop-exit apply.

Mode A mag langdurig draaien zonder Mode B. Als stop-breach optreedt terwijl Mode B uit staat, blijft de bot bij preview/reporting en mag hij niet zelf market-exiten.

## Permanente Verboden Zonder Expliciete ACK

- Geen Coinbase submit/cancel/replace/apply.
- Geen `.env` mutatie.
- Geen service stop/restart.
- Geen productie state repair of handmatige lifecycle apply.
- Geen tweede SELL op gereserveerde base of dezelfde positie.
- Geen learning-to-execution direct bridge.
- Geen approved parameter profile activeren zonder exacte hash ACK.
- Geen Mode B flags aanzetten zonder aparte Mode B ACK.

## Safetyregels

- GPT bepaalt strategie, thesis, setup, trend/reclaim/mean-reversion, support/resistance en entry/exit intent.
- Deterministische code bepaalt execution safety: target validity, stale TP, stop-breach, duplicate SELL, oversell, lifecycle apply en stop/market-exit route.
- Coinbase spot heeft geen echte `reduce_only`; base/reservation checks zijn verplicht.
- Open D3 exits moeten een exchange order id hebben voordat lifecycle/stop-exit verder mag.
- Fill evidence is verplicht voordat local apply of terminal closeout mag.
- Bij stop-breach is controlled stop-exit primair; bestaande far-above-market TP wordt stale/blocked evidence en mag geen tweede SELL veroorzaken.

## Testbeleid

- Gebruik gerichte eindtests; geen eindeloze volledige suite tenzij expliciet gevraagd.
- Standaard eindpoort: `python3 -m py_compile` voor geraakte entrypoints plus gerichte pytest-selecties rond readiness, D3 lifecycle, exit policy, single process, atomic writes en nieuwe tools.
- Tests zijn een eindpoort, niet het productdoel. Stop met extra testloops zodra de afgesproken selectie groen is.

## Endurance Run Workflow

- Prepare: `python3 tools/prepare_autonomous_endurance_run.py --hours 24 --json`
- Monitor: `python3 tools/show_autonomous_live_run_status.py --json`
- Report: `python3 tools/write_autonomous_live_run_report.py --since-hours 24 --json-out reports/live_runs/live-run-24h.json`
- Decide: `python3 tools/summarize_autonomous_run_next_steps.py --run-report reports/live_runs/live-run-24h.json --balanced-profile reports/live_learning/balanced-start-profile-candidate.json --json`

## Eindrapportformat

Eindig elke Codex-ronde met:

- uitgevoerde taak
- status/resultaat
- gewijzigde bestanden
- tests/checks
- readiness
- live side effects
- P0/P1/P2/P3 update
- exacte operatoractie
- expliciete stopconditie als er niets meer moet gebeuren
