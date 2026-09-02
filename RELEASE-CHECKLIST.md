# Release-checklist

Deze lijst loop je af vóórdat je een versie van JARVIS uitgeeft. Elk vakje is
een controle die **daadwerkelijk uitgevoerd** moet worden — niet een controle
die je "wel goed zult vinden".

Twee dingen die deze lijst nadrukkelijk **niet** doet:

- Ze eist geen volledig groene testsuite. Ruim honderd tests staan bewust rood:
  dat zijn veiligheidspoorten die dicht horen te staan. Groen maken zou
  betekenen dat je die poorten openzet. Zie [`docs/FAILURES.md`](docs/FAILURES.md).
- Ze laat geen echte orders plaatsen. Geen enkele controle hieronder mag met
  echt geld handelen.

Achter elk vakje staat hoe je het controleert. Waar `[Windows]` staat, kan de
controle alleen op een echte Windows-pc — niet in een testomgeving op Linux.

---

## 1. Installatie

- [ ] **Schone installatie op een pc zonder Python.** `install.bat` toont
      `Python is niet gevonden.` met een genummerde instructie en het venster
      blijft openstaan. `[Windows]`
- [ ] **Installatie met een te oude Python.** `install.bat` toont
      `Python is gevonden, maar is te oud.` en noemt de gevonden versie én de
      gevraagde reeks (3.11 t/m 3.14). `[Windows]`
- [ ] **Installatie zonder Node.js.** De installatie gaat verder; alleen het
      dashboard wordt overgeslagen. De bot werkt. `[Windows]`
- [ ] **Volledige installatie loopt door alle negen stappen** en eindigt met
      een duidelijke afsluitregel. `[Windows]`
- [ ] **Installatie is herhaalbaar.** `install.bat` twee keer achter elkaar
      draaien geeft hetzelfde resultaat en verliest niets. `[Windows]`
- [ ] **Een halverwege afgebroken installatie herstelt zichzelf.** Venster
      sluiten tijdens stap 4, daarna `install.bat` opnieuw: hij loopt door.
      `[Windows]`
- [ ] **Bestaande `.env` blijft intact.** Draai `install.bat` op een installatie
      met een aangepaste `.env`: eigen instellingen, commentaarregels en de
      volgorde blijven staan; alleen wat je opnieuw invult verandert.
      Geautomatiseerd gedekt door de tests op `bot/env_file.py`.
- [ ] **Bestaande handelsgegevens blijven intact.** De mappen `state/` en
      `logs/` worden aangemaakt als ze ontbreken, en nooit geleegd.
- [ ] **Geen hardgecodeerde gebruikerspaden.** `grep -rn "C:\\\\Users\\\\\|/root/apps" --include=*.py --include=*.bat .`
      levert niets op in productie-code.
- [ ] **Alle `.bat`-bestanden staan in CRLF.** `.gitattributes` bevat
      `*.bat -text`; `file *.bat` toont CRLF.
- [ ] **Elk venster blijft open bij een fout.** Geen enkele `.bat` eindigt op
      een foutpad zonder `pause`.

## 2. Runtime

- [ ] **`start.bat` start alle drie de processen** (bedieningsdienst, bewaker,
      bot) en meldt dat pas als ze echt draaien. `[Windows]`
- [ ] **Een bot die na het starten meteen omvalt wordt niet als "gestart"
      gemeld.** De statuscontrole kijkt drie seconden door voordat hij
      `running` zegt. Geautomatiseerd gedekt in
      `control_service/tests/test_real_process_integration.py`.
- [ ] **`stop.bat` stopt netjes**: eerst een vriendelijk stopverzoek, pas
      daarna hard afbreken. Geen halve orders, geen achtergebleven slot.
- [ ] **`restart.bat` doet stoppen en starten** en laat geen dubbele processen
      achter.
- [ ] **`diagnose.bat` verandert niets** en toont per onderdeel READY /
      WARNING / ERROR / OFFLINE met uitleg.
- [ ] **Crash-loop-preventie werkt.** Een bot die steeds crasht wordt herstart
      met oplopende pauzes (5s, 10s, 20s …) en na het maximum stopt de bewaker
      met `restart_limit_reached`. Geautomatiseerd gedekt met echte processen
      in `tests/test_supervisor.py` en de integratietests.
- [ ] **Permanente fouten leiden niet tot herstarten.** Exitcodes 2, 3 en 4
      geven `permanent_error` met een leesbare reden, en géén nieuwe poging.
- [ ] **Netwerkstoringen worden niet als sleutelfout behandeld.** Een
      onbereikbare provider geeft `VERIFICATION_UNAVAILABLE`, nooit
      `CONFIGURATION_ERROR`.
- [ ] **Een bezette poort geeft een leesbare melding.** Zowel de
      bedieningsdienst (8770) als het dashboard (8000) controleren de poort
      vóórdat uvicorn start, en noemen de poort, beide oorzaken en de
      instelling om hem te wijzigen.
- [ ] **De bot overleeft een tijdelijke storing.** Een mislukte cyclus leidt
      tot een oplopende pauze, niet tot afsluiten.

## 3. Security

- [ ] **Geen secrets in de logboeken.** Draai de bot met herkenbare
      nepsleutels en zoek daarna in `logs/`, `state/` en de terminaluitvoer
      naar die waarden. Verwacht: nul treffers.
- [ ] **Geen secrets in de documentatie.** Alle handleidingen gebruiken
      plaatshouders (`JOUW_OPENAI_KEY`, `JOUW_COINBASE_KEY`). Zoeken in de
      `.md`-bestanden naar het voorvoegsel van een OpenAI-sleutel of naar de
      kopregel van een private sleutel levert niets op. Geautomatiseerd gedekt
      in `tests/test_documentation.py`.
- [ ] **Geen secrets in de repository.** `.env` staat in `.gitignore`;
      `git log -p` bevat geen sleutel.
- [ ] **Alles luistert alleen op loopback.** Controleer op de draaiende
      machine dat de luisteradressen `127.0.0.1` zijn en niet `0.0.0.0`.
      Op Linux: `/proc/net/tcp`. Op Windows: `netstat -ano | findstr 8770`.
- [ ] **De bedieningsdienst eist een token** op elk eindpunt behalve `/health`.
      Een verzoek zonder token krijgt 401.
- [ ] **CORS staat alleen `chrome-extension://`-oorsprongen toe.**
- [ ] **Foutmeldingen lekken geen technische details.** De globale
      foutafhandelaar stuurt nooit een stacktrace naar de browser.
- [ ] **Er wordt geen beveiliging omzeild.** Geen MFA-, CAPTCHA- of
      cookie-omzeiling; geen automatisch aanmaken van API-sleutels.
- [ ] **Er worden geen echte orders geplaatst tijdens installatie of tests.**
      De sleutelcontrole is uitsluitend lezend.
- [ ] **Live-handelspoorten staan dicht in de standaardconfiguratie.**
      Controleer `.env.example`: `EXECUTION_MODE=paper`,
      `ENABLE_LIVE_ENTRY_ORDERS=false`, `ENABLE_LIVE_LIMIT_ORDERS=false`,
      `ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE=false`.
- [ ] **Geen enkele bestaande veiligheidscontrole is verzwakt.** Vergelijk met
      de vorige versie: `bot/order_store.py` en de gate-logica ongewijzigd.

## 4. Extension

- [ ] **De extensie laadt zonder fouten** in `chrome://extensions` met
      ontwikkelaarsmodus aan. Geen rode foutmelding onder de kaart.
- [ ] **Manifest V3** met alleen de rechten `storage` en `alarms`; de
      host-rechten beperkt tot de loopback-poort.
- [ ] **Alle vier de pictogrammen bestaan** (16, 32, 48, 128 px).
- [ ] **De volledige rondgang werkt**: status opvragen, starten, logboek
      ophalen, sleutels controleren, herstarten, stoppen — zonder JS-fouten in
      de console.
- [ ] **Een draaiende bot wordt als draaiend getoond**, een gestopte als
      gestopt, en een dienst die uit staat geeft
      `JARVIS draait nu niet op deze pc.`
- [ ] **Een verkeerd token geeft** `De toegangssleutel werd niet geaccepteerd.`
      met de verwijzing naar `state/control_token.txt`.
- [ ] **Eén netwerkhapering leidt niet tot een foutmelding.** GET-verzoeken
      worden hooguit twee keer opnieuw geprobeerd; POST-verzoeken **nooit** —
      een tweede start zou een tweede bot kunnen starten.
- [ ] **De instellingenpagina onderscheidt "dienst ligt eruit" van "sleutel
      afgewezen".**

## 5. Tests

- [ ] **De volledige suite is gedraaid** en de uitvoer is bewaard.
- [ ] **Geen nieuwe failures ten opzichte van het register.**
      `python tools/check_no_new_failures.py` geeft exitcode 0.
- [ ] **Het register klopt met de werkelijkheid.** `docs/FAILURES.md` is
      opnieuw gegenereerd met `python tools/build_failure_register.py --run`;
      de aantallen in de kop komen overeen met de opsomming.
- [ ] **Geen enkele bestaande test is aangepast om hem groen te maken.** Elke
      aanpassing aan een bestaande test staat gemotiveerd in het bestand zelf
      en gaat over een fout in de test, niet over een fout in de code.
- [ ] **Geen enkele test is overgeslagen, uitgezet of in quarantaine gezet** om
      een release erdoor te krijgen.
- [ ] **CI draait op elke push en pull request** (`.github/workflows/ci.yml`),
      op Python 3.11 en 3.12, en faalt bij een nieuwe regressie.
- [ ] **De documentatietests slagen**: elke genoemde link, elk genoemd
      `.bat`-bestand en elke gedocumenteerde instelling bestaat echt.
- [ ] **Wat niet getest kon worden, staat eerlijk vermeld** in
      [`RELEASE-CANDIDATE.md`](RELEASE-CANDIDATE.md). Een statische controle
      wordt daar nooit gepresenteerd als een echte Windows- of Chrome-test.

---

## Ondertekening

| | |
|---|---|
| Versie | |
| Datum | |
| Doorlopen door | |
| Windows-versie waarop getest | |
| Chrome-versie waarop getest | |
| Openstaande punten | |

Een release gaat alleen door als elk vakje is aangevinkt óf als een niet
aangevinkt vakje hierboven expliciet is opgeschreven als bekende beperking.
