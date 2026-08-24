# AI-TRADINGBOT

A Coinbase Advanced Trade **spot** trading bot. A multi-agent LLM analysis
chain (market-data feature packs, specialist analysts, bull/bear debate,
synthesizer, final judge) proposes trade ideas; a separate deterministic
risk/safety layer decides what is actually allowed to reach Coinbase.
**The AI layer can propose; only the deterministic layer and explicit
operator ACKs can authorize a live action.**

## ⚠️ Status and risk disclaimer

- This bot can place **real orders with real money** on Coinbase when
  `EXECUTION_MODE=live` and the relevant `ENABLE_*` flags are set. The
  checked-in [`.env.example`](.env.example) defaults to **paper mode with
  every live-order, live-exit, market-order and parameter-mutation flag set
  to `false`.** Nothing in this repository activates live trading by
  itself — you must deliberately configure and ACK every gate described
  below.
- This is **not financial advice** and comes with **no warranty of any
  kind**. Cryptocurrency trading carries a substantial risk of loss. If you
  run this against a real Coinbase account, you do so entirely at your own
  risk.
- The code is published for transparency/review. See [License](#license)
  for usage terms — this is **not** an open-source license grant.

## How it works (high level)

```
market data / feature pack
  -> gatekeeper
  -> pending intents / watchlist
  -> specialist analysts -> bull/bear debate -> synthesizer -> final judge
  -> deterministic risk layer
  -> trade plan / execution intent
  -> governed live entry bridge (post-only BUY)
  -> order store -> lifecycle reconciliation -> fill-to-position
  -> position executor plan (D.2)
  -> exit preview / controlled live exit (D.3)
  -> dynamic cancel/replace/trailing (D.4)
  -> execution learning (D.5)
  -> shadow outcome accelerator  [every decision → 1h/4h/24h hypothetical eval, evidence-only]
```

Key architectural rule: the LLM/agent layer can generate ideas, intents and
narratives, but every transition from "idea" to "an order reaches
Coinbase" is gated by deterministic Python code — target validity, stale
take-profit checks, stop-breach handling, duplicate-sell/oversell
prevention, lifecycle/fill evidence requirements, and explicit
operator-approval (`*_ACK`) environment variables for every higher-risk
capability (controlled stop-exit apply, market orders, parameter-profile
activation, GrowBot/River governor changes).

Safety defaults that ship in this repo:

- `REPLICATION_ENABLED=false` and all replication/lifecycle-replication
  flags disabled.
- `MARKET_ORDER_ENABLED` / `ENABLE_MARKET_ORDERS` / `ALLOW_MARKET_ORDERS`
  all `false`; the only supported live execution paths are governed
  post-only limit BUY entries, reduce-only limit SELL exits, and a
  governed near-market limit-IOC stop-exit for stop-breach closes (see
  "Noodstop-exit" below) — never a true unconstrained market order.
- Live entry sizing scales with the account: each cycle the bot prices total
  portfolio equity (free USDC cash plus the market value of every held
  asset) and sizes new BUY entries at `MIN_POSITION_PCT_OF_PORTFOLIO`–
  `MAX_POSITION_PCT_OF_PORTFOLIO` of that value (10%–20% by default), not a
  fixed USDC amount. `MIN_LIVE_ORDER_QUOTE_USDC`/`MAX_LIVE_ORDER_QUOTE_USDC`
  (50–100 USDC) remain as the startup/fallback rails, used only before the
  first successful portfolio pricing.
- An autonomous parameter governor (GrowBot/River bridge) can only ever
  *propose* parameter changes through the existing approved-profile/hash-ACK
  route; it has no independent apply or Coinbase-submit authority.

## Repository layout

| Path | Contents |
|---|---|
| `bot/` | Core bot package: config, LLM clients, strategy engine, execution planners, risk/safety gates, GrowBot/River learning and governor bridge. |
| `tools/` | Operator-facing CLIs: read-only status reports, preflight checks, governed apply/prepare scripts. |
| `tests/` | Test suite (pytest). |
| `docs/` | Architecture notes, runbooks, and phase-by-phase design/decision records. |
| `replication/` | Optional secondary-server replication client (disabled by default). |
| `fixtures/` | Static test fixtures (e.g. product rules). |
| `deploy_templates/` | Example systemd `.service`/`.timer` units for optional sidecars. |
| `scripts/` | One-off operational scripts. |
| `run_trader_loop.py` | Main long-running entrypoint. |
| `.env.example` | Every environment variable the bot reads, with safe placeholder/paper-mode defaults. |

Runtime-only material — real credentials, logs, state, backups, and
generated reports — is intentionally **not** part of this repository (see
[`.gitignore`](.gitignore)).

## Requirements

- Python `3.12` (see [`.python-version`](.python-version))
- A Coinbase Advanced Trade (CDP) API key/secret if you intend to run
  against the live or sandbox API
- Optional: OpenAI / Anthropic / DeepSeek API keys, depending on which LLM
  providers you enable

## Setup

**Windows, zonder programmeerervaring:** volg
[`INSTALLATIE-WINDOWS.md`](INSTALLATIE-WINDOWS.md). Dubbelklik
`INSTALLEREN-WINDOWS.bat` om te installeren en `START-JARVIS.bat` om te
starten; de rest van deze paragraaf is dan niet nodig.

**Handmatig (macOS, Linux, of Windows via de opdrachtprompt):**

```bash
git clone git@github.com:Drent301/AI-TRADINGBOT.git
cd AI-TRADINGBOT
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m tools.setup_wizard          # vraagt om je API keys, schrijft .env (0600)
python -m tools.setup_wizard --check --online   # verifieert ze read-only
```

De wizard maakt `.env` aan vanaf `.env.example` en vult alleen de
credentials in. `EXECUTION_MODE` blijft op `paper` en elke
live-order/live-exit/market-order vlag blijft `false` tot je de
veiligheidsdocumenten in `docs/` hebt gelezen en de gates begrijpt.

Je kunt `.env` ook nog steeds met de hand bewerken (`cp .env.example .env`);
de wizard is een hulpmiddel, geen vereiste.

## Stap-voor-stap handleiding

Expliciete installatie. 
"Setup"-blok hierboven. Volg de stappen in deze volgorde.

### Stap 0 — wat je nodig hebt voordat je begint

- Een computer met Linux, macOS of Windows (met WSL) en een terminal.
- Python 3.12 geïnstalleerd (`python3 --version` om te checken).
- Git geïnstalleerd (`git --version`).
- Een Coinbase Advanced Trade account, en als je echt wil gaan handelen: een
  API key/secret van Coinbase (CDP). **Dit is niet verplicht om te beginnen**
  — de bot kan ook volledig in "paper mode" draaien zonder dat je ooit een
  Coinbase key hoeft aan te maken.
- Optioneel: een API key van OpenAI en/of Anthropic, als je de LLM-analyse
  daadwerkelijk wil laten draaien (zonder key kun je de code wel lezen en de
  paper-structuur bekijken, maar de AI-analyse zelf heeft een key nodig).

### Stap 1 — de code ophalen

```bash
git clone git@github.com:Drent301/AI-TRADINGBOT.git
cd AI-TRADINGBOT
```

Zit je niet vertrouwd met SSH-keys voor git? Gebruik dan de HTTPS-variant:

```bash
git clone https://github.com/Drent301/AI-TRADINGBOT.git
cd AI-TRADINGBOT
```

### Stap 2 — een geïsoleerde Python-omgeving aanmaken

Een "virtual environment" (venv) zorgt ervoor dat de packages van deze bot
niet vermengd raken met andere Python-projecten op je systeem.

```bash
python3 -m venv .venv
source .venv/bin/activate   # op Windows: .venv\Scripts\activate
```

Je terminal-prompt begint nu meestal met `(.venv)` — dat betekent dat de
omgeving actief is. Dit moet je elke keer opnieuw doen als je een nieuwe
terminal opent en de bot wil gebruiken.

### Stap 3 — dependencies installeren

```bash
pip install -r requirements.txt
```

Dit duurt de eerste keer een paar minuten. Foutmeldingen over een te oude
Python-versie betekenen dat je Python 3.12 moet installeren (zie
[`.python-version`](.python-version)).

### Stap 4 — je eigen configuratiebestand aanmaken

De begeleide weg:

```bash
python -m tools.setup_wizard
```

De wizard maakt `.env` aan vanaf `.env.example`, vraagt om je OpenAI- en
Coinbase-credentials, slaat ze op met rechten `0600` (alleen jij kunt ze
lezen) en controleert daarna meteen of ze bruikbaar zijn. Invoer wordt niet
op het scherm getoond en nergens gelogd. Enter indrukken laat een bestaande
waarde ongemoeid.

Voor Coinbase heb je het JSON-bestand nodig dat je downloadt bij het aanmaken
van een CDP API-key:

- veld `name` → **Coinbase API Key**
- veld `privateKey` → **Coinbase API Secret**

Beide sleuteltypes die Coinbase uitgeeft werken: ECDSA (een PEM-blok) en
Ed25519 (een base64-tekst).

Status opvragen zonder iets te wijzigen:

```bash
python -m tools.setup_wizard --check            # alleen vorm/aanwezigheid
python -m tools.setup_wizard --check --online   # ook echt tegen de API's
```

De `--online`-variant doet uitsluitend read-only aanroepen: `GET /v1/models`
bij OpenAI en de accountlijst bij Coinbase. Er wordt nooit een order geplaatst.

Wil je het liever met de hand doen, dan kan dat nog steeds: `cp .env.example .env`
en het bestand openen in een editor. Vul **alleen** de velden in die je nodig
hebt:

- `COINBASE_API_KEY` en `COINBASE_API_SECRET` — laat deze gerust leeg/placeholder
  zolang je alleen in paper mode test. Je hebt ze pas nodig zodra je echt
  live wilt gaan (en dat is een grote, losse beslissing, zie Stap 7).
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` — vul minstens één van deze in als je
  wilt dat de AI-analyseketen (zie verderop) echt LLM-aanroepen doet.
- `EXECUTION_MODE=paper` — **laat dit zo staan**. Dit is de belangrijkste
  schakelaar in het hele bestand: zolang dit op `paper` staat, kan de bot
  nooit een echte order naar Coinbase sturen, wat er ook verder in `.env`
  staat.
- Alle `ENABLE_*`/`*_ACK` velden — laat deze allemaal op hun veilige
  `false`/leeg default staan. Dit zijn de individuele "deuren" die je later,
  één voor één en bewust, kunt openen (zie Stap 7).

Bewaar het bestand. `.env` staat in `.gitignore`, dus die wordt nooit
per ongeluk meegecommit.

### Stap 5 — de bot voor het eerst draaien (paper mode)

```bash
PYTHONPATH=. python3 run_trader_loop.py
```

In paper mode analyseert de bot echte marktdata en doorloopt hij de volledige
beslisketen, maar plaatst hij **geen** echte orders. Je ziet logging in de
terminal en in de map `logs/` (die niet wordt meegecommit). Stop de bot met
`Ctrl+C`.

### Stap 6 — kijken wat de bot heeft gedaan, zonder iets te wijzigen

De bot heeft een hele set "read-only" rapportagetools: scripts die alleen
bestaande state/logs uitlezen en samenvatten, zonder ooit zelf iets te
wijzigen of naar Coinbase te sturen. Voor een beginnende gebruiker zijn dit
de veiligste manieren om te begrijpen wat er gebeurt:

```bash
# overzicht van de huidige open orders en posities
PYTHONPATH=. python3 tools/show_open_orders.py --json

# status van de autonome live-run als geheel
PYTHONPATH=. python3 tools/show_autonomous_live_run_status.py --json

# wat heeft de bot achteraf geleerd/gereflecteerd?
PYTHONPATH=. python3 tools/show_reflection_learning_status.py --json

# parametervoorstellen vanuit de GrowBot/River-laag
PYTHONPATH=. python3 tools/show_growbot_river_learning_status.py --json

# shadow outcome accelerator: hoeveel hypothetische beslissing-uitkomsten zijn er al?
PYTHONPATH=. python3 tools/show_shadow_outcome_learning_status.py --json
```

Elk script accepteert `--json` voor machine-leesbare output, of zonder die
vlag voor leesbare tekst.

### Stap 7 — testen draaien (controleren of alles werkt)

```bash
pip install -r requirements-dev.txt
PYTHONPATH=. python3 -m pytest -q
```

Dit voert de hele testsuite uit op je eigen machine, los van Coinbase. Een
groene testrun betekent dat je installatie consistent is met de codebase.

### Stap 8 — de stap naar live trading (alleen als je dit echt wilt en begrijpt)

Dit is **niet** een volgende "normale" stap — het is een aparte, risicovolle
beslissing die je alleen zet als je de werking (zie de uitgebreide uitleg
hieronder) en de gevolgen begrijpt. In grote lijnen:

1. Lees eerst de relevante runbook(s) in `docs/` voor het onderdeel dat je
   wilt activeren (bijv. `docs/D3_OPEN_EXIT_OPERATOR_RUNBOOK.md` voor
   verkooporders).
2. Vul je echte `COINBASE_API_KEY`/`COINBASE_API_SECRET` in.
3. Zet `EXECUTION_MODE=live`.
4. Zet **alleen** de specifieke `ENABLE_*`-vlag aan die bij de stap hoort die
   je wilt nemen (bijv. eerst alleen live entries, niet meteen alles).
5. Vul de bijbehorende `*_ACK`-omgevingsvariabele in met exact de gevraagde
   bevestigingstekst — dit is een bewuste, expliciete "ik begrijp het risico"
   handtekening, geen technische formaliteit.
6. Houd de order- en positiegrootte aan de veilige kant: live entries worden
   standaard geschaald naar `MIN_POSITION_PCT_OF_PORTFOLIO`–
   `MAX_POSITION_PCT_OF_PORTFOLIO` van je totale portfolio-waarde (standaard
   10%–20%), met `MIN_LIVE_ORDER_QUOTE_USDC`/`MAX_LIVE_ORDER_QUOTE_USDC`
   (50–100 USDC) als vaste fallback zolang portfolio-pricing nog niet is
   gelukt (bijv. direct na opstarten). Zie de sectie "Orderomvang" hieronder
   voor de volledige uitleg.

Doe dit stapsgewijs, één laag per keer, en gebruik de read-only tools uit
Stap 6 vóór en na elke wijziging om te controleren wat er feitelijk gebeurt.

### Troubleshooting (veelvoorkomende problemen)

| Probleem | Mogelijke oorzaak |
|---|---|
| `ModuleNotFoundError` bij het starten | Je hebt de venv niet geactiveerd (Stap 2) of `pip install` niet (opnieuw) gedraaid (Stap 3). |
| Geen LLM-output / lege analyses | Geen geldige `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` in `.env`. |
| Bot stopt met `SETUP REQUIRED` of `CONFIGURATION ERROR` | De credential-preflight blokkeert de start. De melding noemt precies welke waarde ontbreekt of onbruikbaar is; herstel met `python -m tools.setup_wizard`. |
| `COINBASE_API_SECRET heeft een onbekend formaat` | De waarde is geen PEM-blok en geen base64-sleutel. Neem het veld `privateKey` uit het Coinbase-JSON-bestand letterlijk over, zonder aanhalingstekens en zonder afgebroken regels. |
| `COINBASE_API_SECRET lijkt een PEM-sleutel maar kon niet worden gelezen` | Het `-----BEGIN`/`-----END`-blok is onvolledig, of de regeleindes staan niet als `\n` in `.env`. |
| Netwerk- of DNS-fouten richting `api.coinbase.com` | Dit is een netwerk/sandbox-probleem, geen handelssignaal — de bot behandelt een onbekende Coinbase-status altijd als "fail-closed" (geen actie), nooit als impliciete toestemming. |
| Bot doet niets in live mode | Waarschijnlijk ontbreekt een van de vereiste `ENABLE_*`-vlaggen of de bijpassende `*_ACK`. Dat is bedoeld gedrag: elke laag moet apart en expliciet open gezet worden. |
| Tests falen direct na clonen | Controleer je Python-versie (`python3 --version` moet 3.12 zijn) en of `requirements-dev.txt` is geïnstalleerd. |

## Configuration

All configuration is environment-variable driven (see [`bot/config.py`](bot/config.py)
and [`.env.example`](.env.example) for the authoritative, fully-documented
list). Never commit a real `.env` — it is excluded via `.gitignore`.

Start in `EXECUTION_MODE=paper`. Moving any flag from the safe
`.env.example` defaults toward live trading is a deliberate, individually
reviewed decision — read the relevant doc in `docs/` for that subsystem
before flipping it.

De set gevolgde tickers wordt bepaald door `ALLOWED_TICKERS` /
`PHASE_C_ALLOWED_TICKERS` in je eigen `.env`. Op dit moment draait de live
bot met een bewust kleiner universum — `BTC-USDC, ETH-USDC, SOL-USDC,
LINK-USDC` — in plaats van de bredere lijst in `.env.example`.

## Running

```bash
PYTHONPATH=. python3 run_trader_loop.py
```

Read-only operator status tools (safe to run at any time, no side effects):

```bash
PYTHONPATH=. python3 tools/show_autonomous_live_run_status.py --json
PYTHONPATH=. python3 tools/show_full_autonomous_run_readiness.py --json
PYTHONPATH=. python3 tools/show_growbot_river_governor_bridge_status.py --json
PYTHONPATH=. python3 tools/show_growbot_river_learning_status.py --json
PYTHONPATH=. python3 tools/show_shadow_outcome_learning_status.py --json
```

## Diepgaande uitleg: hoe de bot daadwerkelijk werkt

Deze sectie gaat dieper in op elke stap uit het diagram in
["How it works"](#how-it-works-high-level): de AI-agentlagen, hoe orders
worden geplaatst en gevolgd, het tradingplan, de exitstrategie, trailing
stoploss, en hoe de bot achteraf leert en parameters laat aanpassen via
GrowBot/River. Voor de volledige, gedetailleerde architectuur blijft
[`docs/COINBASE_BOT_ARCHITECTURE_AND_FUNCTIONS.md`](docs/COINBASE_BOT_ARCHITECTURE_AND_FUNCTIONS.md)
de bron van waarheid; dit is de toegankelijke samenvatting daarvan.

### De volledige workflow, end-to-end

```
marktdata / feature pack
  -> gatekeeper (goedkope prefilter)
  -> specialist analysts -> bull/bear debat -> synthesizer -> final judge
  -> deterministische risk/safety-laag
  -> tradingplan (D.2) / execution intent
  -> gecontroleerde live entry (post-only BUY, C.4.3)
  -> order store -> lifecycle reconciliation (C.4.4) -> fill-to-position (C.4.5)
  -> positie-executieplan (D.2, opnieuw met echte fill-data)
  -> exit preview / gecontroleerde live exit (D.3, reduce-only SELL)
  -> dynamische cancel/replace/trailing (D.4, vandaag nog preview-only)
  -> execution learning & reflectie (D.5)
  -> shadow outcome accelerator  [elke beslissing → 1h/4h/24h hypothetische eval, evidence-only]
  -> GrowBot/River parameter-sidecar -> Autonomous Parameter Governor
```

De rode draad: **elke pijl naar rechts is een aparte, deterministische
goedkeuringsstap**. Een idee van de AI-laag erft geen rechten — het moet bij
elke stap opnieuw langs harde code-checks, en bij de risicovolste stappen
ook langs een expliciete menselijke ACK in `.env`.

### De AI-agentlagen

De bot gebruikt geen losse "ene LLM-aanroep beslist alles"-aanpak, maar een
keten van gespecialiseerde lagen die elkaar controleren:

1. **Feature pack** — per ticker wordt eerst een feitenbasis opgebouwd: OHLCV
   en indicatoren (EMA, ADX, RSI, Bollinger Bands, Donchian), regime- en
   structuurcontext, orderbook/microstructuur, risk-engine state, en eventueel
   nieuws/sentiment. Dit feature pack is de gedeelde, controleerbare basis
   voor alle volgende lagen — niemand "verzint" cijfers later in de keten.
2. **Gatekeeper** — een goedkope, snelle prefilter in `StrategyEngine` die elke
   ticker classificeert als *reject*, *wait/watch* of *kandidaat voor verdere
   analyse*. Doel: dure LLM-aanroepen besparen en spot-only-regels meteen
   afdwingen. De gatekeeper kan een setup terugzetten op de watchlist, maar
   geeft **nooit** zelf toestemming om te handelen.
3. **Specialist analysts** — los van elkaar beoordelen een trend-specialist,
   breakout-specialist, mean-reversion-specialist en regime/context-specialist
   dezelfde data, elk met een eigen afgebakende JSON-output. Deze specialisten
   delen per cyclus hetzelfde grote dossier (feature pack, chart-patronen,
   reflecties, beslissingsuitkomsten); dat gedeelde blok wordt daarom als
   eerste bericht verstuurd en de kleine, specialist-specifieke instructie als
   laatste (`bot/llm_clients.py::json_response`, `payload_first=True`), zodat
   OpenAI's automatische prompt-caching het over alle specialisten in de
   cyclus kan hergebruiken — dit verlaagt de kosten van de grootste
   LLM-aanroepgroep zonder de promptinhoud zelf te wijzigen.
4. **Bull/bear debat** — een bull- en een bear-redenaar maken bewust de
   tegengestelde argumenten expliciet zichtbaar, in plaats van één gemiddelde
   mening te verzinnen.
5. **Synthesizer** — combineert dat debat tot één samenhangende these:
   `setup_type`, `composite_confidence`, `primary_thesis`, `why_now`,
   `key_trigger` en `invalidation` (het punt waarop de hele these ongeldig
   wordt).
6. **Final judge** — de laatste AI-beslisser. Hij krijgt niet alleen de
   analyse, maar ook het feature pack, bestaande positiecontext,
   chart-patronen, recente reflecties, eerdere beslissingsuitkomsten én een
   concreet `trade_plan` van de planner. Zijn output is altijd één van:
   `approve_trade`, `wait`, `reject`, `reduce_size`, `close_position`. Bij
   tegenstrijdige signalen kiest de architectuur bewust voor de
   voorzichtigste optie (`wait`/`reject`).
7. **Deterministische risk-laag** — de bot vertrouwt geen van de
   bovenstaande AI-output blind. `StrategyEngine._hard_risk_gate(...)` en de
   omliggende safety-laag toetsen hard op: positielimieten, max notional,
   beschikbaar saldo, minimumgrootte, cooldown/`trading_disabled`,
   duplicate-order-bescherming via de `OrderStore`, geen short-posities, geen
   "naked sell", geen averaging-down, en een vereiste bestaande positie voor
   `reduce_size`/`close_position`. **De AI stelt voor; deze laag bepaalt of
   het voorstel überhaupt uitvoerbaar is.**

### Orders plaatsen (live entry)

Een goedgekeurd `BUY`-voorstel bereikt Coinbase via de gecontroleerde
entry-brug (`bot/phase_c43_autonomous_entry_live.py`, fase **C.4.3**):

- Altijd een **post-only limit BUY** — nooit een market order, en nooit een
  SELL vanuit deze brug.
- Gerailde orderomvang die meeschaalt met je portfolio: standaard 10%–20%
  van de totale accountwaarde (zie "Orderomvang: percentage van de
  portfolio-waarde" hieronder voor de volledige uitleg).
- Elke order wordt lokaal geregistreerd in de `OrderStore`, met een mapping
  tussen `client_order_id` en het door Coinbase teruggegeven
  `exchange_order_id`.
- Reject-hardening: als Coinbase de order weigert of `success=false`
  teruggeeft, blijft die order nooit ten onrechte als "open" in de lokale
  state staan.
- Het plaatsen van de order maakt **nog geen positie** aan — een positie
  ontstaat pas na bewezen fill (zie hieronder).

### Orderomvang: percentage van de portfolio-waarde

De deterministische sizing-laag (`bot/dynamic_entry_sizing.py`, aangeroepen
vanuit `bot/strategy_engine.py::_apply_portfolio_based_entry_sizing`)
bepaalt zelf het uiteindelijke bedrag van elke live BUY. De LLM-planner en
-judge rapporteren wel een `size_quote`/`max_size_quote`, maar dat is altijd
een **niet-autoritatieve placeholder** — deze code kiest het echte bedrag,
niet de AI-laag.

- Elke cyclus prijst `StrategyEngine._compute_portfolio_value_usdc()` de
  totale accountwaarde: vrij USDC-saldo plus de marktwaarde van elk
  aangehouden asset (via het nieuwe `CoinbaseClient.get_all_balances()`),
  gewaardeerd tegen de `<ASSET>-USDC`-feature packs die diezelfde cyclus al
  zijn opgehaald. Een asset zonder feature pack die cyclus telt voor **0**
  mee in plaats van geraden te worden — dit kan de portfolio-waarde alleen
  onderschatten, nooit overschatten, dus het blijft aan de veilige kant.
- `MIN_POSITION_PCT_OF_PORTFOLIO`/`MAX_POSITION_PCT_OF_PORTFOLIO` (standaard
  `0.10`/`0.20`, dus 10%–20%) bepalen welk deel van die portfolio-waarde als
  nieuwe BUY-orderomvang mag worden ingezet.
- Binnen die bandbreedte bepaalt dezelfde kwaliteitsscore als voorheen
  (confidence, edge, reward/fee, reward/risk, orderbook, spread, setup,
  trend, support/resistance, regime en learning-signalen) waar in de band
  de order precies valt — een sterke setup dicht bij het maximum, een
  marginale setup dicht bij het minimum. De gewichten van die score zijn
  ongewijzigd; ze worden nu gelezen als fractie (0..1) van de geconfigureerde
  bandbreedte in plaats van als vaste USDC-bedragen.
- Zolang de portfolio nog niet geprijsd is (bijv. direct na opstarten, of
  een mislukte Coinbase-balansaanroep), valt de bot terug op de vaste
  `MIN_DYNAMIC_ENTRY_QUOTE_USDC`/`MAX_DYNAMIC_ENTRY_QUOTE_USDC` (standaard
  50–100 USDC), zodat er nooit stilzwijgend op een onbekende of nul-waarde
  wordt gesized.
- Elke live cyclus worden **tien** velden op `cfg` mee-bijgewerkt naar
  dezelfde portfolio-percentage-waarden: `MIN_LIVE_ORDER_QUOTE_USDC`/
  `MAX_LIVE_ORDER_QUOTE_USDC`, de C.4.3/autonomous-caps
  (`PHASE_C_MAX_ORDER_QUOTE`, `AUTONOMOUS_MAX_ORDER_QUOTE`), `MAX_NOTIONAL_USD`,
  `DEFAULT_QUOTE_SIZE_USDC`, en de exit-caps `PHASE_D3_MAX_EXIT_ORDER_QUOTE`/
  `CONTROLLED_STOP_EXIT_MAX_QUOTE_USD` — inclusief de D.3-exit-vloer én
  -plafond, zodat een groter account automatisch een grotere exit-onder- én
  bovengrens krijgt, en een stop-loss op een grotere positie niet meer kan
  worden geblokkeerd door een verouderd vast bedrag.
- Er is geen hardcoded absoluut dollarplafond meer op entries of exits: de
  vroegere `MAX_LIVE_ORDER_QUOTE_USDC=100`/`MAX_LIVE_EXIT_ORDER_QUOTE_USDC=120`-
  clamps in `bot/live_order_size_policy.py`, `phase_c43_autonomous_entry_live.py`
  en `phase_d3_controlled_live_exits.py` zijn verwijderd — die constanten
  dienen alleen nog als fallback-default zolang `cfg` geen waarde heeft (vóór
  de eerste cyclus). 10–20% van het portfolio is dus de enige echte grens.
- Bekijk de geprijsde portfolio-waarde en de daaruit afgeleide caps per
  cyclus in `state/portfolio_value.jsonl`.

Relevante `.env`-variabelen (zie ook [`.env.example`](.env.example)):

| Variabele | Standaard | Betekenis |
|---|---|---|
| `MIN_POSITION_PCT_OF_PORTFOLIO` | `0.10` | Ondergrens van een nieuwe BUY-entry, als fractie (10%) van de totale portfolio-waarde. |
| `MAX_POSITION_PCT_OF_PORTFOLIO` | `0.20` | Bovengrens van een nieuwe BUY-entry, als fractie (20%) van de totale portfolio-waarde. |
| `MIN_DYNAMIC_ENTRY_QUOTE_USDC` | `50.00` | Vaste USDC-fallback-ondergrens, alleen gebruikt zolang portfolio-pricing nog niet is gelukt. |
| `MAX_DYNAMIC_ENTRY_QUOTE_USDC` | `100.00` | Vaste USDC-fallback-bovengrens, alleen gebruikt zolang portfolio-pricing nog niet is gelukt. |
| `MIN_LIVE_ORDER_QUOTE_USDC` / `MAX_LIVE_ORDER_QUOTE_USDC` | `50.00` / `100.00` | Startup-waarden; worden elke live cyclus overschreven naar de actuele portfolio-percentage-caps (geen hardcoded plafond meer). |
| `MAX_NOTIONAL_USD` | `100.00` | Startup-waarde; wordt elke live cyclus overschreven. Voorheen bleef dit vast en blokkeerde `amount_cap_guard.py` elke BUY boven 100 USDC, ook nadat de portfolio-cap hoger lag. |
| `PHASE_D3_MAX_EXIT_ORDER_QUOTE` / `CONTROLLED_STOP_EXIT_MAX_QUOTE_USD` | `120.00` / `120.00` | Startup-waarden voor de full-close- resp. stop-loss-exitcap; worden elke live cyclus overschreven zodat een grotere positie ook volledig (en met een werkende stop-loss) gesloten kan worden. |

### Orders monitoren (lifecycle-bewaking)

Een geplaatste order verdwijnt niet uit beeld na het plaatsen. Fase **C.4.4**
(`bot/phase_c43_lifecycle_orchestrator.py`,
`bot/phase_c44_poll_to_apply_closeout.py`) bewaakt de status:

- Eerst altijd een **read-only snapshot** van de actuele Coinbase-orderstatus.
- Zolang de status `OPEN`/`open` is, is de enige toegestane actie
  `keep_open` — er gebeurt dan lokaal niets.
- Bij `CANCELLED`, `EXPIRED` of `REJECTED` kan een closeout via een apply-stap
  worden afgehandeld, maar altijd eerst als **dry-run preview**, en alleen
  echt toegepast met een expliciete operator-ACK.
- Een fill wordt nooit aangenomen op basis van een netwerk- of DNS-fout: een
  onbekende of mislukte statuscheck wordt altijd **fail-closed** behandeld
  (geen actie), nooit geïnterpreteerd als "dus wel gevuld" of "dus wel
  geannuleerd".
- Operator-tools om dit zelf te bekijken (read-only):
  `tools/show_open_orders.py`, `tools/show_phase_c43_lifecycle_governance.py`,
  `tools/show_phase_c40_live_order_safety.py`.

Pas wanneer fase **C.4.5** (`bot/phase_c45_live_fill_pilot.py`) een echte fill
bewijst — met fees, `fill_count` en `avg_fill_price` — wordt de order lokaal
omgezet in een echte positie (`position_created`). Ook die overgang vereist
een eigen, aparte ACK.

### Het tradingplan (D.2 — position executor plan)

Zodra er een bewezen positie is, bouwt fase **D.2**
(`bot/phase_d2_position_executor.py`) het tradingplan voor die positie. Dit
is *bracket-lite planning* — het plant de hele exit-structuur, maar plaatst
zelf nog geen enkele order. Het plan bevat:

- entry/`entry_price` als referentiepunt;
- de invalidatie/stop-prijs;
- TP1 en TP2 (twee winstnemingsniveaus, waarbij het systeem afdwingt dat TP2
  nooit onder TP1 ligt);
- een "runner"-deel (het restant dat na TP1/TP2 nog open blijft voor verdere
  winst);
- trailing-activatieprijs en trailing-afstand (input voor D.4, zie verder);
- een tijdslimiet voor de positie;
- een minimum-stopafstand (`STOP_DISTANCE_PCT`, standaard 2%): als de
  LLM-judge een stop teruggeeft die dichter op de entry ligt dan deze vloer,
  verbreedt `_derive_entry_protective_levels()`
  (`bot/phase_c43_autonomous_entry_live.py`) de stop automatisch naar de
  vloer — nooit strakker, nooit een reject van de trade, puur een
  deterministische veiligheidsmarge ná wat de LLM voorstelde;
- een fee-bewuste minimum-netto-edge-check, zodat een plan niet wordt
  uitgevoerd als de verwachte winst de fees niet eens dekt;
- een harde regel: **geen averaging down**;
- coherentie tussen plan, positie en een unieke fingerprint, zodat een
  verlopen of inconsistent plan niet per ongeluk wordt uitgevoerd.

Het exit-doel (`exit_target_source_policy.py`) kiest, in prioritievolgorde:
een expliciete marktcontext-/GPT-target, live 1h-support/resistance
(`build_d2_exit_market_context()`, hergebruikt dezelfde
`MarketDataService.build_feature_pack()` die ook de entry-kant al gebruikt),
het trade-plan-doel, de positie's eigen TP-velden, of tot slot een vaste
risk/reward-vuistregel. Marktcontext wordt alleen doorgegeven wanneer er al
een live Coinbase-client beschikbaar is (dezelfde bestaande poll-toestemming
als de rest van deze fase — geen nieuwe autorisatie); ontbreekt of mislukt
die, dan valt het systeem net zo veilig terug als voorheen. Zodra een positie
gevuld is, blijft de lifecycle-service dit ook op elke volgende cyclus
opnieuw proberen zolang er nog geen `D2_PLAN_STATUS_READY`-plan is opgeslagen
— eerder stopte dit voorgoed zodra de bijbehorende entry-order niet meer
lokaal "open" was, ook als het plan zelf nooit geslaagd was.

### Exitstrategie en het plaatsen van verkooporders (D.3)

Fase **D.3** (`bot/phase_d3_controlled_live_exits.py`) vertaalt het D.2-plan
naar een daadwerkelijke, gecontroleerde spot-SELL:

- **Altijd preview-only eerst** — er wordt eerst getoond wat er zou gebeuren,
  voordat er iets wordt verstuurd.
- **Eén veilig exit-intent per cyclus**, nooit meerdere SELL's tegelijk voor
  dezelfde positie.
- Spot heeft geen ingebouwde "reduce-only" optie zoals futures dat kennen,
  dus D.3 bouwt dat zelf met lokale boekhouding:
  - `position_size_base` = beschikbare/niet-gereserveerde hoeveelheid;
  - `bot_managed_base` = beschikbaar + gereserveerd;
  - `reserved_base_open_exit_orders` = som van alle al openstaande
    exit-reserveringen.
  Dit voorkomt **oversell** (meer verkopen dan je daadwerkelijk hebt) en
  **dubbele exits** op dezelfde positie.
- Orderomvang wordt afgerond op de echte Coinbase product-increments
  (`base_increment`, `price_increment`, `min_order_quote`) vóór verzending.
- Trailing-gebaseerde live submits zijn op dit moment nog geblokkeerd totdat
  D.4 (zie hieronder) verder is uitgewerkt.
- Net als bij entries is een echte verkooporder pas mogelijk met de juiste
  `ENABLE_LIVE_EXIT_ORDERS`/`ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT`-vlaggen én
  een expliciete ACK.
- Lifecycle-bewaking na het plaatsen volgt dezelfde filosofie als bij
  entries: `OPEN` blijft `keep_open`; `PARTIAL`/`FILLED`/`CANCELLED`/
  `EXPIRED`/`REJECTED` gaan eerst door een dry-run en pas daarna, met ACK,
  door een apply-stap.
- Voor lang openstaande exits bestaat extra "stale/open"-governance
  (`cancel_candidate_preview_only`, `replace_candidate_preview_only`): zelfs
  het annuleren en vervangen van een order gebeurt nooit atomisch in één
  stap, maar altijd eerst cancel, dan een nieuwe preview, om te voorkomen dat
  de boekhouding van gereserveerde hoeveelheden inconsistent raakt.
- Bekijk de actuele open exits en hun status met:
  `tools/show_phase_d3_open_exit_monitor.py`,
  `tools/show_phase_d3_live_exit_order_snapshot.py`,
  `tools/show_phase_d3_open_exit_order_governance.py`.

### Noodstop-exit (Mode B, `bot/controlled_stop_market_exit_plan.py`)

Naast de normale D.3-route (post-only limit SELL, geduldig) heeft de bot een
**apart, strenger gegate pad** voor het moment dat een positie haar stop/
invalidatie-niveau breekt: een **near-market limit-IOC** (immediate-or-
cancel) SELL via `sor_limit_ioc`, zodat er nooit een resting order achterblijft
die niet meteen vult. Dit pad activeert alleen als **alle** onderstaande
voorwaarden tegelijk waar zijn (Mode A, preview-only, blijft anders de
default):

- `ENABLE_CONTROLLED_STOP_MARKET_EXITS`,
  `ENABLE_AUTONOMOUS_STOP_EXIT_CANCEL`, `ENABLE_AUTONOMOUS_STOP_EXIT_SUBMIT`
  en `ENABLE_AUTONOMOUS_STOP_EXIT_APPLY` staan alle vier op `true`;
- een exacte `MODE_B_CONTROLLED_STOP_EXIT_ACK`-string in `.env`;
- een daadwerkelijk gedetecteerde stop-breach op de positie zelf.

De volgorde is altijd: eerst een eventuele bestaande take-profit-order
cancellen en die cancel bevestigen, dán pas de IOC-verkooporder voorbereiden
en versturen, en pas na bevestigd fill-bewijs de lokale positie sluiten.
Prijs en hoeveelheid worden afgerond op de echte Coinbase-productprecisie
vóór verzending, en een fill-verificatie na het versturen doet een korte
retry (i.p.v. één enkele meting) omdat een net gevulde order soms nog
kortstondig `OPEN` teruggeeft voordat de matching engine dat heeft bijgewerkt.

Dit pad werd op 2026-07-08 voor het eerst in productie geraakt door een echte
stop-breach en onthulde daarbij vier samenhangende bugs (verkeerd
Coinbase-API-veld, een crash op de echte orderrespons-vorm, ontbrekende
prijsafronding, en een race condition in de fill-check) — alle vier gefixt en
met regressietests afgedekt. Zie de git-historie rond die datum voor de
volledige post-mortem.

### Trailing stoploss (D.4)

Trailing stoploss bestaat vandaag als **preview-only scaffold**
(`docs/D4_TRAILING_PREVIEW_SCAFFOLD.md`) — er wordt nog **niets live**
gecancelled, vervangen of verstuurd op basis van trailing-logica. Het
ontwerp werkt als volgt, zodra het ooit live geactiveerd wordt:

- Een trailing stop wordt pas "actief" zodra de prijs een
  `activation_price`/`activation_pct` voorbij de entry beweegt.
- Eenmaal actief, registreert het systeem een `peak_reference_price` (de
  hoogste/beste prijs sinds activatie) en berekent het een
  `trailing_stop_price` op basis van een vaste `trailing_distance_pct` onder
  (of boven, bij short-achtige exits) die piek.
- Zolang de prijs binnen de trailing-afstand blijft, of binnen een kleine
  `refresh_tolerance_pct` schommelt, blijft de bestaande order gewoon staan
  (`keep_open`).
- Pas als de prijs voldoende terugvalt na de piek, genereert het systeem een
  `preview_reprice_candidate` — een voorstel om de bestaande exit-order te
  cancellen en te vervangen door een nieuwe, scherpere prijs. Dat voorstel
  vereist altijd een **toekomstige, expliciete ACK** voordat het echt mag
  worden uitgevoerd.
- Ingebouwde blockers voorkomen een trailing-candidate bij: een stale/oude
  market snapshot, een actieve cooldown, een candidate die onder
  `min_order_quote` zakt, een candidate die het orderboek zou "kruisen"
  (niet meer post-only-veilig is), of wanneer de huidige exit al deels is
  gevuld (die moet dan eerst via de normale D.3-lifecycle).
- Kortom: trailing stoploss is in deze codebase een **voorgesteld**
  cancel/replace-mechanisme, niet een automatisch zelfstandig actief
  systeem — het volgt dezelfde "voorstellen, nooit zelf uitvoeren"-filosofie
  als de rest van de bot.

### Shadow Outcome Accelerator — snellere parameterleerbasis

De grootste bottleneck voor parameteroptimalisatie is het gebrek aan
beslissings-uitkomst-data: elke gesloten trade levert één evidence-punt op,
maar de bot neemt tientallen `wait`/`reject`/`no_plan`-beslissingen per dag
die normaal geen uitkomst hebben. De **Shadow Outcome Accelerator**
(`bot/shadow_outcome_accelerator.py`) lost dat op door *elke* full-cycle
ticker-beslissing automatisch vast te leggen en later hypothetisch te evalueren:

- Bij elke cycle-run wordt voor elke ticker een shadow record aangemaakt met de
  volledige beslissingscontext (beslissing, scores, regime, trade-plan niveaus,
  feature pack snapshot).
- Automatisch worden drie evaluatiemomenten ingepland: **1h, 4h en 24h** na de
  beslissing. Op elk moment wordt de lokale prijs-/candledata gebruikt om te
  bepalen wat er hypothetisch zou zijn gebeurd (MFE/MAE, `missed_opportunity`,
  `bad_trade_avoided`, of `unclear`).
- De uitkomsten worden opgeslagen als append-only JSONL in
  `state/shadow_decision_outcomes.jsonl` (nooit gecommit — zie `.gitignore`).
- Evidence wordt gefilterd op kwaliteitstier: `high` (candles + entry levels),
  `medium` (candles only), `low` (price only), `insufficient` (te weinig data).
  Alleen `medium`/`high` evidence wordt als bruikbaar voor GrowBot/River
  aangemerkt.
- GrowBot/River leest shadow evidence via `load_shadow_evidence_for_river()` als
  read-only invoer — de feed heeft expliciet geen execution-bevoegdheid
  (`allowed_use: evidence_only_no_execution_authority`).
- Uitschakelbaar via `ENABLE_SHADOW_OUTCOME_ACCELERATOR=false` in `.env`
  (standaard: `true`). Fouten in de shadow-laag propageren nooit naar de
  trading-flow (fail-open).

**Harde garanties** (alle getest):
- Geen Coinbase API-aanroepen.
- Geen live orders, geen cancel/replace.
- Geen BotConfig-mutatie, geen `.env`-writes, geen profile-activatie.
- Ontbrekende candle/price-data degradeert naar `insufficient_data`, nooit een
  fout in de tradingflow.

Bekijk de huidige stand:
```bash
PYTHONPATH=. python3 tools/show_shadow_outcome_learning_status.py
PYTHONPATH=. python3 tools/show_shadow_outcome_learning_status.py --json
PYTHONPATH=. python3 tools/show_shadow_outcome_learning_status.py --write-reports
```

### Hoe de bot leert en reflecteert

Na elke afgesloten cyclus (trade, gemiste kans, of bewuste WAIT) evalueert de
bot zichzelf achteraf, zonder dat dit ooit live invloed heeft op een lopende
order:

- **Reflection Learning Context** (`docs/REFLECTION_LEARNING_CONTEXT.md`)
  labelt elke beslissing achteraf als bijvoorbeeld `correct_wait`,
  `missed_opportunity`, `too_strict_wait`, `correct_avoid`,
  `false_signal_avoided`, `good_trade`, `bad_trade`, `early_entry`,
  `overtrading_risk` of `insufficient_evidence`. Belangrijk:
  een prijsstijging alleen is **nooit** genoeg om iets een
  "gemiste kans" te noemen — er gelden strikte anti-hindsight-regels (de
  trigger moest al zichtbaar zijn op het moment van de beslissing, entry/exit
  moesten plausibel vulbaar zijn, het verwachte voordeel moest de fees,
  spread en slippage overstijgen, enzovoort). Deze laag kan zelf **niets**
  goedkeuren, blokkeren of muteren — puur rapportage.
- **Adaptive Policy Lab** bouwt hierop verder: het aggregeert de
  reflection-labels per setup, blocker, ticker en marktregime, en mag pas
  bij voldoende samplegrootte, effectgrootte, richtingstabiliteit over
  meerdere rapportages en regime-diversiteit een report-only
  parameter-candidate voorstellen. Ook deze candidate is per definitie
  `safe_to_activate_now=false` totdat een operator hem apart beoordeelt.
- **Neural Shadow Policy** (`docs/NEURAL_SHADOW_LEARNING.md`) is een lokaal
  getraind, eenvoudig schaduwmodel dat leert van dezelfde lokale logs en een
  zachte voorspelling toevoegt aan de beslissingscontext (bijv.
  `prefer_no_trade` met een confidence-score). Dit model heeft **expliciet
  geen** execution-bevoegdheid (`execution_allowed=false` is een harde
  configuratie-check) en kan de judge of D.2/D.3 niet blokkeren of forceren.
  Let op: dit trainingsbestand wordt niet automatisch ververst (alleen via
  het losse `tools/train_neural_shadow_policy.py`) — met te weinig recente
  of te eenzijdige samples valt het terug op één enkele, weinig informatieve
  klasse, wat de code zelf al signaleert (`one_class_dataset_warning`).
- **GrowBot/River leert alleen van wat er daadwerkelijk in
  `logs/trade_reflections.jsonl` terechtkomt** — sluit je een positie ooit
  buiten de normale D.2/D.3-flow om (bijv. een handmatige noodreconciliatie),
  zorg dan dat je alsnog een reflectie voor die trade toevoegt, anders is die
  trade voor het leersysteem onzichtbaar. De state-schema van deze laag
  (`bot/growbot_river_learning_contract.py: ALLOWED_STATE_KEYS`) is bewust
  klein en expliciet whitelisted, en groeit incrementeel: `adx_1h`
  (trendsterkte/keuzigheid, los van `trend_strength` dat alleen
  prijsverandering meet) is op 2026-07-08 toegevoegd na een verlies-post-mortem
  waarbij precies dat signaal wél in de bull/bear-analyse zat maar nergens in
  het leergeheugen — puur additief, geen enkele blokkade leest dit veld nog.

### Parameters aanpassen via GrowBot/River en de Autonomous Parameter Governor

De bot kan zijn eigen parameters laten "leren bijstellen", maar altijd via
een lange keten van afzonderlijke goedkeuringen — er is geen route waarbij
een leeralgoritme direct een live parameter wijzigt:

```
reflectie/uitkomsten
  -> Reflection Learning Context (labels, geen actie)
  -> Adaptive Policy Lab (report-only candidate)
  -> GrowBot/River-sidecar (extra bewijs + bounded parametervoorstellen)
  -> parameter_candidate_analysis
  -> Autonomous Parameter Governor (validatie, bounded activatie)
  -> approved_parameter_profile (exacte hash-ACK vereist)
  -> BotConfig (de echte, actief gebruikte instellingen)
```

**GrowBot/River-sidecar** (`docs/GROWBOT_RIVER_LEARNING_INTEGRATION.md`,
`bot/growbot_learning_adapter.py`) zet bestaande logs om in "episodes"
(state = feature pack + regime, action = parameterkeuze, reward = netto PnL
of fee-/fill-kwaliteit) en houdt daar een incrementeel model op bij — met
River's eigen `learn_one`/`predict_one` API als die geïnstalleerd is
(zie [`requirements-river-sidecar.txt`](requirements-river-sidecar.txt), een
losse, optionele omgeving), anders een deterministische statistische
fallback. Dit gebeurt gefaseerd via `bot/parameter_step_scheduler.py`:
ruwe `coarse_tuning`-voorstellen (5–15% stappen) leveren pas na genoeg
episodes en regimes `stabilization` (2–5%) en uiteindelijk `fine_tuning`
(0,25–2%, max 1 parameter per voorstel) op. **Geen van deze voorstellen heeft
zelf uitvoeringsbevoegdheid** — elk rapport zet expliciet
`parameter_mutation_allowed=false` en `execution_authority=false`.

**Autonomous Parameter Governor** (`docs/AUTONOMOUS_PARAMETER_GOVERNOR.md`,
`bot/growbot_river_governor_bridge.py`) is de enige laag die een candidate
ooit daadwerkelijk mag activeren, en dat nog altijd bounded:

- `can_authorize_orders=false` — de governor kan nooit zelf handelen,
  cancellen, vervangen of risk-gates overslaan.
- Activatie kan alleen via een vaste **allowlist** van parameters (zoals
  `PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT`, `MAX_SPREAD_PCT`,
  `EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT`, `STOP_DISTANCE_PCT`) — dit zijn
  uitsluitend risico/exit-*definitie*-parameters (spread-limiet, minimale
  edge/reward-ratio's, stop- en exit-afstand). Sizing/exposure-parameters
  (ordergrootte, max open posities, max orders) zijn hier bewust **niet**
  onderdeel van en blijven altijd handmatig via een operator-goedgekeurd
  profiel; execution-mode-vlaggen, Coinbase-credentials, oversell-guards en
  andere kritieke instellingen staan expliciet op de **forbidden**-lijst en
  zijn nooit autonoom aanpasbaar.
- Activatie wordt geblokkeerd zodra er open orders, open posities of een
  actieve lifecycle-fout zijn.
- Standaard maximaal **1 parameterwijziging per 24 uur**, maximaal 1
  parameter per activatie, en altijd met een backup van het bestaande
  `state/approved_parameter_profile.json` plus een rollback-plan vooraf. Een
  toegepaste wijziging sluit zichzelf pas automatisch af (en laat de
  volgende toe) zodra deze cooldown-periode is verstreken **en** er sindsdien
  geen fouten zijn waargenomen (`evaluate_pending_activation()` in
  `bot/autonomous_parameter_governor.py`) — zonder deze stap zou de governor
  na de allereerste toepassing voorgoed vastlopen.
- De governor-runs zijn beschermd door een lockbestand
  (`state/reflection_adaptive_governor.lock`). Sinds 2026-07-08 wordt een lock
  niet meer alleen op leeftijd als verlopen beschouwd, maar controleert
  `acquire_governor_lock()` ook of het PID van de lockhouder nog leeft
  (`os.kill(pid, 0)`): een verweesd lock van een gecrasht/afgesloten proces
  wordt direct opgeruimd (`stale_reason: dead_pid`) in plaats van tot twee uur
  álle governor-runs — inclusief de cooldown-evaluatie hierboven — te
  blokkeren. Een hergebruikt PID leest als "leeft nog" (de veilige kant: het
  lock wordt dan niet gestolen).
- Drie modi: `report_only` (alleen rapporteren, default), `prepare_only`
  (alleen een pending-plan schrijven) en `apply_when_safe` (mag pas echt
  toepassen als **alle** gates — candidate, hash, cooldown, open-order/
  open-position-check, ACK — groen zijn).
- Zelfs in `apply_when_safe`-modus is een losse, exacte ACK-string in `.env`
  vereist (`AUTONOMOUS_PARAMETER_GOVERNOR_ACK`), en een aparte ACK voor
  rollback.
- De governor werkt `state/approved_parameter_profile.json` bij zodra hij een
  wijziging toepast, maar synchroniseert bewust **nooit** zelf de bijbehorende
  `APPROVED_PARAMETER_PROFILE_HASH` in `.env` — die hash vertegenwoordigt een
  mens die de wijziging goedkeurt, niet de governor zelf. Loop je hierdoor
  een keer op een hash-mismatch, dan valt de bot sinds 2026-07-08 gewoon
  terug op de kale `.env`-waarden in plaats van te crashen bij opstarten
  (`bot/approved_parameter_profile.py`); bekijk het voorgestelde profiel en
  werk de hash pas bij nadat je de wijziging zelf hebt beoordeeld.

Operator-commando's om dit zelf te volgen, allemaal read-only of dry-run
zonder `--apply`:

```bash
PYTHONPATH=. python3 tools/run_growbot_river_learning_cycle.py --json
PYTHONPATH=. python3 tools/show_growbot_river_learning_status.py --json
PYTHONPATH=. python3 tools/show_growbot_river_governor_bridge_status.py --json
PYTHONPATH=. python3 tools/show_autonomous_parameter_governor_status.py --json
```

### Correctie- en hardeningpass (2026-07-08)

Een reeks interne bugfixes na een volledige pijplijn-audit. Ze veranderen géén
van de gedocumenteerde gedragingen hierboven; de **percentage-van-portfolio
sizing blijft volledig ongewijzigd** (`bot/dynamic_entry_sizing.py`,
`StrategyEngine._apply_portfolio_based_entry_sizing`/`_compute_portfolio_value_usdc`
en de `*_PCT_OF_PORTFOLIO`-config zijn niet aangeraakt).

- **Trade-plan-validatie** (`bot/trade_planner.py::is_valid_entry_trade_plan`):
  `take_profit_1` en `do_not_chase_above` zijn niet langer hard verplicht. De
  planner-prompt staat deze velden expliciet toe op `null`; een resting-limit
  BUY vult nooit slechter dan zijn limietprijs (dus een ontbrekend
  chase-plafond is geen kapitaalrisico) en winst-targets worden door de
  exit-/trailing-laag beheerd, niet door TP1. Dit voorkomt dat overigens
  geldige plannen stilzwijgend werden afgekeurd (dezelfde bugklasse als de
  eerdere `valid_trade_plan`-regressie).
- **Setup-type-classificatie** (`bot/strategy_engine.py::_normalize_setup_type`):
  `breakout_retest`, `support_sweep_reclaim`, `failed_breakout` en `range_trade`
  werden eerder allemaal naar `unclear` gebucketd en kregen daardoor de kleinste
  vaste sizing-cap (60 USDC). Ze mappen nu naar hun juiste tier. Dit raakt
  uitsluitend de secundaire, vaste-USDC-clamp `_clamp_judge_buy_size_quote`
  (één `min(...)`-term náást de portfolio-caps), **niet** de
  percentage-van-portfolio-sizing zelf.
- **Positiebewaking-prompt** (`bot/prompts.py`): de toegestane
  `position_watch`-beslissingen in de prompt zijn gelijkgetrokken met de parser
  en escalatielogica (`hold_ok` / `watch_closer` / `tighten_risk` /
  `escalate_full_review`), zodat het model geen tegenstrijdige lijst meer
  krijgt.
- **Indicatoren** (`bot/indicators.py`): RSI geeft nu de canonieke waarde 100
  (in plaats van `NaN`) op een venster zonder verliezen, en de ADX-berekening
  maskeert `-DM` tegen de ruwe `+DM` in plaats van tegen de al-genulde waarde.
- **Learning-hygiëne** (`bot/execution_outcome_tracker.py`): de opgeslagen
  `market_regime`-waarde wordt defensief genormaliseerd, zodat een niet-string
  upstream-waarde nooit een vervormd label in `state/decision_outcomes.json`
  kan lekken.
- **Neurale shadow-features** (`bot/neural_feature_schema.py`): vijf features
  (`rsi_15m`/`rsi_1h`/`adx_1h`/`ema_4h_alignment`/`ema_1d_alignment`) lazen
  verkeerde sleutelpaden en werden stil `0.0`. Ze lezen nu de echte feature-pack
  keys (`indicators.<tf>.rsi_14`/`adx_14`) resp. leiden de klassieke 50/200-EMA-
  alignment af uit `ema_50`/`ema_200`. Dit verbetert alleen de trainingsdata van
  de **shadow-only** neurale laag (`execution_allowed=False`, geen orderbevoegd-
  heid); de live beslissing verandert er niet door.
- **Judge-observability** (`bot/strategy_engine.py::_normalize_judge_payload`):
  de final judge produceert enkele extra velden (`setup_quality_score`,
  `trigger_readiness`, `recommended_entry_type`, `entry_reason`, e.a.) die eerder
  werden weggegooid. Ze worden nu bewaard zodat ze zichtbaar zijn in logs/analyse.
  Uitsluitend velden die door géén enkele gate of prijsberekening worden gelezen
  zijn toegevoegd — het handelsgedrag blijft byte-identiek. Prijs-/risico-velden
  die de planner zouden overschrijven of de approve/wait-drempel zouden verschuiven
  (`preferred_limit_price`, `invalidation_price`, `do_not_chase_above`,
  `entry_zone_*`, `target_price_*`, `cancel_if_price_*`, `support_level`) zijn
  bewust **niet** toegevoegd.

### Parameter-profile hash-pin drift (2026-07-06 t/m 2026-07-09)

De `approved_parameter_profile`-laag (`bot/approved_parameter_profile.py`)
vergelijkt bij elke config-load de sha256 van
`state/approved_parameter_profile.json` met een in `.env` vastgepinde
`APPROVED_PARAMETER_PROFILE_HASH` — die pin staat voor een expliciete
menselijke goedkeuring van een governor-voorstel. Op 2026-07-06 schreef de
`autonomous_parameter_governor` een nieuw profiel weg zonder dat de pin werd
bijgewerkt (dat gebeurt bewust nooit automatisch), waardoor elke load vanaf
dat moment werd afgewezen (`hash mismatch`).

Dat faalt op zichzelf veilig: bij afwijzing valt config-constructie terug op
de kale `.env`-defaults in plaats van te crashen. Dat is zelf ook een fix uit
dezelfde hardeningpas — een eerdere versie liet een afgewezen profiel de hele
`BotConfig()`-constructie laten crashen, wat op 2026-07-08 bijdroeg aan een
stop-breached positie die urenlang zonder monitoring bleef doordat elke
herstart daarna in een crash-loop liep. Maar de drift betekende ook dat elke
governor-tuning sinds 6 juli drie dagen lang nooit live werd toegepast — de
bot draaide stilzwijgend op statische `.env`-waarden in plaats van het
goedgekeurde profiel.

Op 2026-07-09 is de pin herbevestigd tegen het huidige profiel
(`fee_aware_default_quote_50_bounded_v1`, sha256 `d22890f2…`). Praktisch
verschil met de eerdere fallback: alleen `PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT`
verschoof van `0.0125` naar `0.01160458`; de overige elf sizing/risk-
parameters waren al identiek.

## GrowBot/River autonomous parameter tuning

- De GrowBot/River learning-laag is actief: het sidecar-systeem (bot/growbot_river_learning_contract.py, bot/river_online_parameter_learner.py) leert continu uit lokale logs/outcomes en stelt report-only parametervoorstellen voor.
- Daar bovenop is een **fast-start-autotune** tier toegevoegd: een lager-volume readiness-laag voor kleine, omkeerbare D2-parameterstappen, naast de strikte stabilization-route (80%/80% coverage). Zie [`docs/GROWBOT_RIVER_LEARNING_INTEGRATION.md`](docs/GROWBOT_RIVER_LEARNING_INTEGRATION.md) voor de exacte criteria en allowlist. Vandaag op deze fast-start-lijst: `PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT`, `PHASE_D2_MIN_REWARD_TO_FEE_RATIO`, `PHASE_D2_MIN_REWARD_TO_RISK_RATIO`, `MAX_SPREAD_PCT`, `EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT` en `STOP_DISTANCE_PCT`.
- `STOP_DISTANCE_PCT` (minimum stopafstand) is deze sessie van een niet-actieve registry-placeholder naar een echt, live afgedwongen én leerbaar parameter gemaakt: `bot/growbot_learning_adapter.py` herkent nu wanneer een positie werd gestopt terwijl de koers nadien alsnog gunstig bewoog (`false_positive_plan` + `mfe_pct >= 1%`) als bewijs om de stopafstand te verruimen — bovenop het bestaande signaal om te verkrappen na een diepe drawdown.
- **Trailing stoploss-parameters** (`PHASE_D2_DEFAULT_TRAILING_ACTIVATION_PCT`/`_DISTANCE_PCT`) worden wél door `BotConfig` gelezen, maar sturen alleen het D.2-previewveld `trailing` aan — de daadwerkelijke trailing-berekening in `bot/position_manager.py` gebruikt eigen, hardgecodeerde per-setup-standaarden en kent geen `cfg` door. Beide parameters staan (nog) niet op de governor-/approved-profile-/fast-start-allowlists en hebben geen GrowBot/River-bewijs — een vergelijkbaar gat als `STOP_DISTANCE_PCT` vóór deze sessie, nog niet gedicht.
- `bot/growbot_river_readiness.py` rapporteert nu exact welke `stabilization_ready`-blockers *echt* zijn (`real_blockers`/`real_blockers_summary`) versus welke alleen een permanente, niet-blokkerende upstream-status melden. Zodra de River-sidecar beschikbaar is (`river_available=true`) verdwijnt `growbot_upstream_learning_runtime_unavailable` uit de actieve blockers en verschijnt het uitsluitend nog als `historical_readiness_labels`-item (`status: historical_stale_label_not_an_active_blocker`) — het reflecteert alleen de permanente GrowBot-upstream licentie/runtime-status, niet of de bot zelf kan leren. Op dit moment zijn `feature_snapshot_coverage_below_80pct` en `market_regime_coverage_below_80pct` de enige echte blockers, en die zijn `awaiting_live_episode_volume`: ze lossen automatisch op met meer live episodes, zonder code- of operatoractie.
- Elke parameterwijziging loopt uitsluitend via de bestaande, ongewijzigde route: `GrowBot/River proposal → parameter_candidate_analysis → autonomous_parameter_governor → approved_parameter_profile → BotConfig`. Er is geen parallelle apply-route en geen directe `.env`-mutatie door deze laag.
- `state/approved_parameter_profile.json` wordt pas door `BotConfig` geaccepteerd als de lokale `.env`-variabele `APPROVED_PARAMETER_PROFILE_HASH` exact overeenkomt met de SHA-256 van dat bestand — dit is een bewuste, losse goedkeuringsstap die altijd lokaal en handmatig blijft.
- `.env` bevat dus de actuele, geldige `APPROVED_PARAMETER_PROFILE_HASH` voor deze installatie, maar **wordt nooit gepubliceerd**: het staat in [`.gitignore`](.gitignore) en wordt nooit gecommit of naar GitHub gepusht.
- In de publieke repository staat uitsluitend [`.env.example`](.env.example) met veilige placeholder-waarden — elke operator genereert en bewaart zijn eigen `.env` en bijbehorende profile-hash lokaal.

## Adaptive learning intelligence (GrowBot/River depth layer)

Bovenop de bestaande GrowBot/River-leerlaag hierboven is een **report-only**
verdiepingslaag toegevoegd: per-parameter bewijs, proposal-tiers, een
overfit-risicomodel en regime/ticker-coverage. Dit is **geen** nieuw,
parallel leersysteem — GrowBot/River blijft de bron van waarheid, en de
bestaande approved-profile/governor-route blijft het enige apply-pad.

De **Shadow Outcome Accelerator** (zie boven) is een aanvullende evidence-bron
voor deze laag: in plaats van te wachten op gesloten trades (n=1 op dit
moment) levert hij hypothetische 1h/4h/24h-uitkomsten van *elke*
ticker-beslissing. GrowBot/River leest die evidence als read-only invoer —
zonder enige execution-bevoegdheid — zodat de parameterleerbasis veel sneller
groeit dan met alleen gerealiseerde trades.

Zie [`docs/ADAPTIVE_LEARNING.md`](docs/ADAPTIVE_LEARNING.md) voor de volledige
uitleg, inclusief hoe rapporten handmatig te regenereren en hoe het dashboard
te starten om ze te bekijken.

## Tradingbot Control Center (read-only dashboard)

A read-only web dashboard — live status, GrowBot/River learning readiness, parameter
proposals, opportunity radar, agent decision trace, positions/orders, risk guards,
logs, and reports — lives in [`dashboard/`](dashboard/README.md). It is local-only
(binds `127.0.0.1`, reachable via SSH tunnel), reuses the existing `tools/show_*.py`
status scripts and report/state files, and has no code path that can write `.env`,
mutate state, call Coinbase, or restart anything. See
[`dashboard/README.md`](dashboard/README.md) for setup, run commands, and the full
security notes.

The dashboard never imports `bot/config.py` or reads `.env` directly (see
`dashboard/backend/config.py`); to still know which tickers the running bot
actually follows, `run_trader_loop.py` publishes a small, secret-free
`state/runtime_ticker_universe.json` at startup. Positions, the opportunity
radar and the trade-thesis view use it to hide closed/historical entries for
tickers no longer in `ALLOWED_TICKERS` (e.g. after narrowing the ticker list) —
an open position always stays visible regardless, since it still needs
monitoring/exit. The Overview page shows the currently tracked tickers as
badges, sourced from `/api/status/tickers`.

## Testing

```bash
pip install -r requirements-dev.txt
PYTHONPATH=. python3 -m pytest -q
```

For a faster, targeted check during development, compile the modules you
touched and run the related test files rather than the full suite — see
[`AGENTS.md`](AGENTS.md) for the project's own test policy.

## Documentation

`docs/` contains detailed architecture notes, operator runbooks, and
phase-by-phase design records (entry/exit lifecycle, learning pipeline,
parameter governance, etc.). Start with
[`docs/COINBASE_BOT_ARCHITECTURE_AND_FUNCTIONS.md`](docs/COINBASE_BOT_ARCHITECTURE_AND_FUNCTIONS.md)
for the full system description, and
[`docs/ADAPTIVE_LEARNING.md`](docs/ADAPTIVE_LEARNING.md) for the adaptive
learning intelligence / proposal-tier / overfit-risk layer built on top of
[`docs/GROWBOT_RIVER_LEARNING_INTEGRATION.md`](docs/GROWBOT_RIVER_LEARNING_INTEGRATION.md).

## License

Copyright © Drent301. All rights reserved.

This source code is published for transparency and review only. No
license is granted to use, copy, modify, merge, publish, distribute,
sublicense, or sell copies of this software, in whole or in part, without
prior written permission from the copyright holder.

## Disclaimer

Nothing in this repository constitutes financial, investment, or trading
advice. Use of this software with real funds is entirely at your own risk.
