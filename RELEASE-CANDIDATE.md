# Release Candidate

Dit document beschrijft wat er in deze versie is veranderd, wat er
daadwerkelijk is getest, en — even belangrijk — wat er **niet** getest kon
worden. Het is bedoeld om eerlijk te zijn over de staat van de software, niet
om hem te verkopen.

| | |
|---|---|
| **Versie** | 1.0.0-rc.1 |
| **Datum** | 2 september 2026 |
| **Basis** | de aangeleverde ZIP van AI-TRADINGBOT / JARVIS |
| **Status** | release candidate — installeerbaar en bruikbaar, nog niet op een echte Windows-pc bevestigd |

---

## Wijzigingen

Geen bestaande functionaliteit is verwijderd. De handelslogica, de
beslissingsketen en alle veiligheidspoorten zijn ongewijzigd overgenomen uit de
ZIP. Wat erbij is gekomen, gaat over installeren, draaiend blijven en bedienen.

### Installatie voor een niet-programmeur

- `INSTALLEREN-WINDOWS.bat` — één bestand om op te dubbelklikken, in negen
  stappen, met leesbare uitleg bij elke fout. Het venster blijft altijd open
  als er iets misgaat.
- Vier bedieningsbestanden: `START-JARVIS.bat`, `STOP-JARVIS.bat`,
  `HERSTART-JARVIS.bat`, `DIAGNOSE-JARVIS.bat`, met korte snelkoppelingen
  (`install.bat`, `start.bat`, `stop.bat`, `restart.bat`, `diagnose.bat`).
- `tools/check_python.py` controleert de Python-versie (3.11 t/m 3.14) vóórdat
  er iets geïnstalleerd wordt, in plaats van halverwege stuk te lopen.
- De installatie is herhaalbaar: opnieuw draaien herstelt wat ontbreekt en
  laat bestaande instellingen en gegevens ongemoeid.

### Draaiend blijven

- `bot/resilience.py` — herprobeerbeleid en circuit breaker: een tijdelijke
  storing leidt tot wachten en opnieuw proberen, niet tot afsluiten.
- `bot/supervisor.py` — een bewaker die de bot herstart met oplopende pauzes
  (5s, 10s, 20s …), stopt na tien herstarts binnen een uur
  (`restart_limit_reached`), en bij een permanente fout (verkeerde instelling,
  dubbele bot, afgewezen sleutels) helemaal niet herstart.
- `bot/health_check.py` — een diagnose die per onderdeel READY, WARNING, ERROR
  of OFFLINE meldt, met advies in gewone taal. Een controle die zelf omvalt
  laat de rest gewoon doorlopen.
- `run_trader_loop.py` gebruikt nu een oplopende pauze bij opeenvolgende
  fouten in plaats van een vaste minuut.

### Bedienen vanuit Chrome

- `control_service/` — een lokale dienst op `127.0.0.1:8770` met tokenauth op
  elk eindpunt behalve `/health`, en CORS uitsluitend voor
  `chrome-extension://`-oorsprongen.
- `extension/` — een Manifest V3-extensie met alleen de rechten `storage` en
  `alarms`, die start, stopt, herstart, status toont, logregels ophaalt en
  sleutels laat controleren.

### Documentatie

- [`README.md`](README.md) — herschreven voor een lezer zonder
  programmeerkennis. De oude technische inhoud is niet weggegooid maar
  verplaatst naar [`docs/TECHNISCHE-README.md`](docs/TECHNISCHE-README.md).
- [`HANDLEIDING-WINDOWS.md`](HANDLEIDING-WINDOWS.md) — stap voor stap, met
  uitleg bij elk scherm.
- [`PROBLEMEN-OPLOSSEN.md`](PROBLEMEN-OPLOSSEN.md) — alle bekende problemen in
  tabelvorm.
- [`RELEASE-CHECKLIST.md`](RELEASE-CHECKLIST.md) — de lijst die vóór een
  uitgave wordt afgelopen.
- [`docs/FAILURES.md`](docs/FAILURES.md) — het failure-register, gegenereerd
  uit een echte testrun.

### Gerepareerde defecten

Elf echte defecten. Negen zijn gevonden door de software te draaien en bewezen
door de reparatie terug te draaien en de test opnieuw te zien falen; de laatste
twee zijn gevonden doordat CI op een andere machine draait dan deze — als
gewone gebruiker en met systemd — en zijn onder diezelfde omstandigheden
nagespeeld en daarna opgelost gemeten:

1. `RetryPolicy.from_env` negeerde omgevingsvariabelen — de code-standaard
   overschreef de ingestelde waarde.
2. Een zombieproces werd als draaiend gerapporteerd (`os.kill(pid, 0)` slaagt
   op een zombie), waardoor `stop.bat` "JARVIS reageert niet" meldde na een
   geslaagde stop.
3. Een bot die vlak na het starten omviel, werd als succesvol gestart gemeld.
4. De melding bij een bezette poort werd nooit getoond: uvicorn vangt de
   bindfout zelf af, dus de foutafhandeling eromheen was dode code.
5. `%errorlevel%` binnen een haakjesblok in `START-JARVIS.bat` — cmd.exe vult
   die in bij het lezen, niet bij het uitvoeren.
6. De snelkoppeling `diagnose.bat` verwees naar een bestand dat alleen in
   hoofdletters van hem verschilde. Windows maakt dat onderscheid niet, dus
   riep het bestand zichzelf aan; het diagnosebestand heet nu
   `DIAGNOSE-JARVIS.bat`.
7. De gezondheidscontrole meldde geïnstalleerde pakketten als ontbrekend.
8. `NameError` in het foutpad van de gezondheidscontrole.
9. De extensie meldde "JARVIS draait nu niet op deze pc" na één netwerkhapering.
10. De replica-audit viel om met een `PermissionError` op iedere machine waar
    de gebruiker geen beheerder is. Een van de standaard zoekpaden ligt onder
    `/root`, en `Path.exists()` geeft daar geen `False` maar een fout:
    het slikt alleen "bestaat niet", niet "geen toegang".
11. `systemctl show` op een unit die systemd niet kent geeft geen foutcode maar
    `ActiveState=inactive` — precies alsof de dienst bestaat en stilstaat. Op
    elke machine mét systemd maar zónder deze unit meldde de status daardoor
    "de bot draait niet", terwijl er niets gemeten was.

Daarnaast zijn zeven failures uit de ZIP opgelost: vijf door lekkende
teststubs, één ontbrekende methode in een testdubbel en één test die naar een
hardgecodeerd pad (`/root/apps/Crypto/coinbase_bot`) keek.

---

## Testresultaat

| | |
|---|---|
| Gemeten op | 2 september 2026 |
| Python | 3.11.15 (Linux) |
| Commando | `python -m pytest -q` |
| Uitkomst | **2961 geslaagd, 103 gefaald, 3 overgeslagen** |
| Nieuwe failures ten opzichte van de ZIP | **0** |
| Opgeloste failures uit de ZIP | 7 |

De 103 failures worden **niet** als geslaagd gepresenteerd. Ze zijn stuk voor
stuk geclassificeerd in [`docs/FAILURES.md`](docs/FAILURES.md):

| Oordeel | Aantal | Betekenis |
|---|---|---|
| **GATE** | 93 | Een veiligheidsmaatregel doet zijn werk. De bot wordt geleverd met elke live-handelspoort dicht; een test die zo'n poort open verwacht faalt per definitie. Groen maken zou die poort openzetten. |
| **DRIFT** | 5 | Code en testverwachting zijn uit elkaar gelopen. Vereist een inhoudelijk oordeel over de handelsstrategie, geen technische ingreep. |
| **OMGEVING** | 5 | Vereist een `.env` met echte sleutels, die er in een testomgeving bewust niet is. |

`python tools/check_no_new_failures.py` bewaakt de invariant die er wél toe
doet: geen nieuwe failures. Dat draait op elke push via
[`.github/workflows/ci.yml`](.github/workflows/ci.yml), op Python 3.11 en 3.12.

Geen enkele bestaande test is aangepast om hem groen te maken, en geen enkele
test is overgeslagen of uitgezet.

---

## Wat er echt is uitgevoerd

Deze controles zijn met draaiende software gedaan, niet door de broncode te
lezen:

- **Geen secrets in logs.** De bot is gedraaid met herkenbare nepsleutels;
  daarna is in twaalf bronnen gezocht (logbestanden, statusbestanden,
  terminaluitvoer). Nul treffers. `logs/loop.log` was daarbij gevuld
  (3.380 bytes), dus er is echt geschreven.
- **Alleen loopback.** Op kernelniveau bevestigd via `/proc/net/tcp`: de
  dienst luistert uitsluitend op `127.0.0.1`, niet op `0.0.0.0`.
- **Crash-loop-preventie**, met echte processen, vier scenario's: een bot die
  altijd crasht (herstart met oplopende pauze, daarna `restart_limit_reached`),
  exitcode 4 (één start, `permanent_error`), exitcode 0 (`clean_exit`) en een
  onafgevangen uitzondering.
- **Bezette poort**, met echte processen, op zowel de bedieningsdienst als het
  dashboard: de leesbare melding verschijnt en het proces stopt netjes.
- **De volledige rondgang in de extensie**, in een echte Chromium: status,
  starten, logboek, sleutelcontrole, herstarten, stoppen — zonder JS-fouten.
- **Het dashboard bouwt**: `npm ci && npm run build` slaagt en
  `dist/index.html` wordt geserveerd.
- **`.env` blijft behouden**: bij het opnieuw instellen van een sleutel bleven
  bestaande regels, commentaar en volgorde staan.
- **De CI-bewaker doet wat hij belooft**: een kunstmatig toegevoegde failure
  gaf exitcode 1, een kunstmatig verwijderde bekende failure exitcode 2. En hij
  heeft zich meteen bewezen: de eerste echte CI-run vond twee defecten die op
  deze machine niet optreden, omdat hier als beheerder en zonder systemd
  gedraaid wordt.
- **De suite als gewone gebruiker (uid 65534), met een systemd die de unit niet
  kent** — dezelfde omstandigheden als de bouwmachine: 103 gefaald, nul nieuwe
  failures. Vóór de reparatie faalden hier drie tests extra.
- **CI staat groen** op Python 3.11 en 3.12, plus de aparte controle op
  extensie, batchbestanden en documentatie. Dat is groen in de betekenis die
  hier telt: nul nieuwe failures ten opzichte van het register — de 103
  verklaarde failures staan nog steeds rood, en horen dat te doen.

---

## Beperkingen

Dit is de eerlijke lijst. Niets hiervan is met een statische controle
"aangetoond"; wat er niet staat, is niet gedaan.

### Niet getest, en dat kon ook niet

- **Windows.** Alle ontwikkeling en alle tests draaiden op Linux. De
  `.bat`-bestanden zijn geanalyseerd, hun logica is nagebouwd in
  `tests/test_windows_compatibility.py` (157 tests over quoting, CRLF,
  `chcp 65001`, vertraagde variabele-expansie en foutpaden), maar **er heeft
  nooit een echte `install.bat` op een echte Windows-pc gedraaid.** Dat is de
  belangrijkste openstaande controle.
- **Google Chrome.** De extensie is volledig doorlopen in Chromium via
  Playwright. Dat is een goede benadering, maar het is niet Chrome, en de
  handmatige stap "Uitgepakte extensie laden" in `chrome://extensions` is niet
  in Chrome zelf uitgevoerd.
- **Echte API-sleutels.** Er is nooit met een echte OpenAI- of
  Coinbase-sleutel gewerkt. De sleutelcontrole is getest met nepsleutels en met
  een geblokkeerde netwerkverbinding, waarmee de drie uitkomsten (geaccepteerd,
  afgewezen, niet bereikbaar) elk zijn afgedwongen — maar niet tegen de echte
  dienst.
- **Echte orders.** Er is nooit een order geplaatst, ook geen testorder. De bot
  is uitsluitend in papieren modus gedraaid. Dat blijft de standaard.
- **Langdurig draaien.** De langste ononderbroken run duurde minuten, niet
  dagen. Geheugengroei of langzame lekken over een week zijn niet gemeten.

### Bekende beperkingen die blijven

- **De 103 failures blijven rood.** Dat is een keuze, geen omissie. 93 daarvan
  zijn gesloten veiligheidspoorten en die blijven dicht. De 5 DRIFT-gevallen
  vragen een oordeel over de handelsstrategie dat niet bij een installatie- en
  stabiliteitstraject hoort.
- **Het dashboard heeft Node.js nodig.** Zonder Node.js werkt de bot volledig,
  maar is er geen webpagina met grafieken.
- **De extensie moet handmatig geladen worden.** Hij staat niet in de Chrome
  Web Store; laden gebeurt via ontwikkelaarsmodus.
- **Eén pc, één bot.** Er is geen ondersteuning voor meerdere bots naast
  elkaar op dezelfde poorten.

---

## Statusoverzicht

| Onderdeel | Status | Toelichting |
|---|---|---|
| **Windows-installatie** | Klaar, niet op Windows bevestigd | Negen stappen, herhaalbaar, leesbare fouten. Logica gedekt door 157 tests; een echte Windows-run ontbreekt. |
| **Chrome-extensie** | Werkend in Chromium, niet in Chrome | Volledige rondgang zonder fouten; Manifest V3; alleen `storage` en `alarms`. |
| **API-sleutels** | Werkend met nepsleutels | Drie uitkomsten correct onderscheiden; uitsluitend lezende controle; nooit tegen de echte dienst getest. |
| **Security** | Gecontroleerd | Loopback-only bevestigd op kernelniveau; tokenauth; geen secrets in logs, documentatie of repository; geen stacktraces naar de browser. |
| **Stabiliteit** | Gecontroleerd met echte processen | Herprobeerbeleid, circuit breaker, bewaker met crash-loop-preventie, permanente fouten zonder herstart. |
| **Gegevens en instellingen** | Behouden | `.env` blijft intact bij herinstallatie; `state/` en `logs/` worden nooit geleegd. |
| **Live handelen** | Uit | `EXECUTION_MODE=paper`; alle live-schakelaars staan op `false` en zijn in dit traject niet aangeraakt. |

---

## Aanbevolen volgende stap

Draai [`RELEASE-CHECKLIST.md`](RELEASE-CHECKLIST.md) af op een echte
Windows-pc met een echte Chrome. Dat is precies het gat tussen deze release
candidate en een release: de logica is gedekt, de omgeving nog niet.
