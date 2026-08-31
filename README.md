# JARVIS Trading Bot — handleiding

Een handelsbot voor Coinbase die op je eigen Windows-pc draait. Je hebt geen
enkele programmeerkennis nodig om hem te installeren en te gebruiken.

> **Ben je wél programmeur?** De technische documentatie staat in
> [`docs/TECHNISCHE-README.md`](docs/TECHNISCHE-README.md): architectuur, alle
> instellingen, de veiligheidslagen en hoe de beslissingsketen werkt.

---

## ⚠️ Lees dit eerst

Deze bot kan **echte orders plaatsen met echt geld**. Dat gebeurt niet vanzelf:
in de standaardinstellingen staat elke schakelaar voor live handelen op `false`
en draait de bot in *papieren modus* — hij denkt na en houdt bij wat hij zóu
doen, maar stuurt niets naar Coinbase.

- Dit is **geen financieel advies** en er is **geen enkele garantie**.
- Handelen in cryptovaluta brengt een aanzienlijk risico op verlies met zich mee.
- Zet je dit tegen een echt Coinbase-account aan, dan doe je dat volledig op
  eigen risico.
- **Begin altijd in papieren modus** en laat hem een tijd meelopen voordat je
  ook maar overweegt iets aan te zetten.

---

## Wat je nodig hebt

| | |
|---|---|
| **Computer** | Windows 10 of Windows 11 |
| **Internet** | Een gewone verbinding |
| **Coinbase** | Een account waar je zelf een API-sleutel aanmaakt |
| **OpenAI** | Een account met een API-sleutel (dit kost geld per gebruik) |
| **Tijd** | Ongeveer 20 minuten voor de installatie |

Python en Node.js hoef je **niet** vooraf te installeren als je ze al hebt. De
installatie controleert het en zegt precies wat er eventueel nog moet gebeuren.

---

## 1. Installeren

1. Pak het gedownloade ZIP-bestand uit. Klik met de rechtermuisknop op het
   bestand en kies **Alles uitpakken**.
2. Open de map die daaruit komt.
3. **Dubbelklik op `install.bat`.**
4. Er opent een zwart venster. Laat het staan en lees mee.

Het venster loopt negen stappen af:

```
[1/9] Python controleren
[2/9] Node.js en npm controleren
[3/9] Python-omgeving klaarzetten
[4/9] Python-pakketten installeren        <- duurt het langst
[5/9] Dashboard bouwen
[6/9] Je API-sleutels instellen           <- hier moet je iets doen
[7/9] Sleutels controleren bij OpenAI en Coinbase
[8/9] Zelftest van de installatie
[9/9] Chrome-extensie voorbereiden
```

**Het venster sluit nooit vanzelf bij een fout.** Gaat er iets mis, dan blijft
het openstaan met een uitleg in gewone taal en wat je eraan kunt doen.

### Ontbreekt Python?

Dan stopt de installatie meteen met een uitleg. Je doet dit:

1. Ga naar <https://www.python.org/downloads/>
2. Download **Python 3.12**.
3. **Belangrijk:** zet tijdens de installatie onderin een vinkje bij
   *"Add python.exe to PATH"* vóórdat je op *Install* klikt.
4. Sluit het zwarte venster en dubbelklik opnieuw op `install.bat`.

Python 3.11 tot en met 3.14 werkt ook. Ouder dan 3.11 werkt niet — de
onderdelen die de bot gebruikt worden daar niet meer voor uitgebracht.

---

## 2. Je API-sleutels

De bot heeft twee sleutels nodig. Die maak je **zelf** aan bij de leveranciers;
niemand anders kan of mag dat voor je doen.

### Coinbase

1. Ga naar <https://portal.cdp.coinbase.com/access/api>
2. Log in en klik op **Create API key**.
3. Kies sleuteltype **ECDSA**.
4. Geef alleen de rechten die je nodig hebt. Voor meelezen is *View* genoeg;
   pas als je later echt wilt laten handelen is *Trade* nodig.
5. Download het JSON-bestand dat Coinbase je geeft.

Tijdens stap 6 van de installatie opent JARVIS deze pagina voor je en pikt het
gedownloade bestand vanzelf op. Lukt dat niet, dan wordt er gewoon om gevraagd.

### OpenAI

1. Ga naar <https://platform.openai.com/api-keys>
2. Klik op **Create new secret key**.
3. Klik op de kopieerknop. JARVIS haalt hem van je klembord.

> **Let op:** OpenAI rekent per gebruik af. Zet een uitgavenlimiet in je
> OpenAI-account voordat je de bot laat draaien.

### Waar komen die sleutels terecht?

In een bestand `.env` in je JARVIS-map, alleen op jouw pc.

- Ze gaan **nooit** naar een andere server dan die van Coinbase en OpenAI zelf.
- Ze staan **nooit** in een logbestand, foutmelding of schermafdruk — overal
  waar iets van een sleutel zichtbaar zou kunnen worden, staat `[REDACTED]`.
- `.env` staat in `.gitignore` en komt dus nooit per ongeluk in een
  broncoderepository terecht.
- Vraagt iemand je ooit om je sleutel in een chat te plakken: doe dat niet.

---

## 3. Werken de sleutels echt?

Een sleutel kan er perfect uitzien en toch niet werken — bijvoorbeeld omdat je
hem later ingetrokken hebt. JARVIS doet daarom bij stap 7 een echte
**leesvraag** aan beide leveranciers. Er wordt daarbij niets gekocht of
verkocht.

Er zijn precies drie uitkomsten, en die betekenen iets heel verschillends:

| Uitkomst | Wat het betekent | Wat je doet |
|---|---|---|
| **Sleutel werkt** | De leverancier accepteert je sleutel. | Niets. Klaar. |
| **Sleutel afgewezen** | De leverancier is bereikbaar maar weigert de sleutel: verlopen, ingetrokken, of te weinig rechten. | Maak een nieuwe sleutel aan. |
| **Niet bereikbaar** | Er kon geen contact gelegd worden: internet eruit, storing bij de leverancier, of een firewall. | Controleer je internet en probeer het later opnieuw. **Er is niets mis met je sleutel.** |

JARVIS zal een netwerkprobleem nooit als "verkeerde sleutel" presenteren. Dat
onderscheid loopt door de hele applicatie heen, tot in de Chrome-extensie.

---

## 4. De bot starten

**Dubbelklik op `start.bat`.**

Wat er gebeurt:

1. Je sleutels worden gecontroleerd (weer alleen leesvragen).
2. De systeemcontrole draait: Python, pakketten, configuratie, sleutels,
   handelsmotor, dashboard, extensie.
3. Er openen twee zwarte vensters — het dashboard en de achtergronddienst.
   **Laat die openstaan; sluiten betekent stoppen.**
4. De bot zelf start onder een bewaker (zie hieronder).
5. Je browser opent op <http://127.0.0.1:8000> met het dashboard.

### De bewaker

De bot draait niet los, maar onder een bewakingsproces. Crasht de bot door een
storing, dan gebeurt dit:

```
crash  ->  in het logboek zetten  ->  netjes opruimen
       ->  even wachten  ->  opnieuw starten  ->  in de gaten houden
```

De wachttijd loopt op (5, 10, 20, 40 seconden…) zodat een leverancier die plat
ligt niet elke seconde opnieuw bestookt wordt. Blijkt de fout niet tijdelijk —
een verkeerde instelling, een ontbrekende sleutel — dan stopt de bewaker
meteen en legt uit wat je moet doen. Herstarten zou daar toch niets oplossen.

Crasht de bot meer dan tien keer binnen een uur, dan houdt de bewaker ermee op
en zegt waar het logboek staat. Zo kan er nooit een eindeloze crashlus ontstaan.

---

## 5. De bot stoppen

**Dubbelklik op `stop.bat`.**

De bot krijgt een *net* stopverzoek en mag een lopende handelscyclus afmaken.
Dat kan een halve minuut duren; dat is de bedoeling. Hard afbreken zou een
halve orderadministratie kunnen achterlaten.

**Herstarten** doe je met `restart.bat`. Die stopt eerst en start daarna pas —
en weigert te starten als het stoppen niet gelukt is, want twee bots die
dezelfde posities beheren is het laatste wat je wilt.

---

## 6. De Chrome-extensie

Met de extensie bedien je de bot vanuit je browser, zonder zwarte vensters.

### Installeren

1. Open Chrome en ga naar `chrome://extensions`
2. Zet rechtsboven **Ontwikkelaarsmodus** aan.
3. Klik op **Uitgepakte extensie laden**.
4. Kies de map **`extension`** in je JARVIS-map.
5. Klik op het JARVIS-icoontje in de werkbalk, dan op **Instellingen**.
6. Open met Kladblok het bestand **`state\control_token.txt`** in je
   JARVIS-map, kopieer de regel en plak hem in het veld *Toegangssleutel*.
7. Klik op **Opslaan** en daarna op **Verbinding testen**.

### Wat de extensie kan

- Zien of de bot draait, opstart, herstelt van een storing of gestopt is.
- Starten, stoppen en herstarten.
- De volledige systeemcontrole bekijken.
- De laatste honderd logregels lezen.
- Je API-sleutels controleren (alleen leesvragen).

Het icoontje in de werkbalk laat de toestand zien: **AAN** (groen), **WACHT**
(oranje, herstelt van een storing), **UIT** (grijs), **!** (rood, gestopt door
een fout) of **?** (de achtergronddienst draait niet).

### Waarom is er een toegangssleutel?

De extensie praat met een klein programma op je eigen pc. Zonder sleutel zou
elke website die je opent dat programma kunnen aanspreken en je bot kunnen
stoppen of starten. De sleutel voorkomt dat.

De sleutel geldt **alleen op jouw pc** en geeft **geen toegang tot je geld** —
dat kan hij niet, want je Coinbase-sleutel zit er niet in en verlaat je
JARVIS-map nooit. Deel hem toch met niemand.

### Waarom staan mijn API-sleutels niet in de extensie?

Omdat browsercode nooit de plek is voor iets geheims. De opbouw is bewust:

```
Chrome-extensie          knoppen en status, geen geheimen
        v
Achtergronddienst        alleen op 127.0.0.1, met toegangssleutel
        v
Bewaker                  start, stopt en herstelt de bot
        v
Handelsmotor             hier zitten de sleutels en de handelslogica
        v
Coinbase
```

Alles wat gevoelig is blijft in de onderste lagen. De extensie kent alleen
knoppen en statussen.

---

## 7. Logboeken

Alle logboeken staan in de map **`logs`** in je JARVIS-map.

| Bestand | Wat erin staat |
|---|---|
| `loop.log` | Wat de bot doet: elke cyclus, elke beslissing, elke fout. |
| `supervisor.log` | Wat de bewaker doet: starten, crashes, wachttijden. |
| `control_service.log` | De achtergronddienst voor de extensie. |
| `loop_errors.jsonl` | Alleen de fouten, met per fout of hij tijdelijk was. |

Je kunt ze openen met Kladblok. Er staan **nooit** sleutels in — alles wat op
een sleutel lijkt wordt vervangen door `[REDACTED]` voordat het opgeschreven
wordt.

Snel de laatste regels bekijken kan ook via de Chrome-extensie, kopje
*Laatste logregels*.

---

## 8. Er gaat iets mis

Draai eerst **`diagnose.bat`**. Die controleert alles en zegt per onderdeel wat
er aan de hand is:

```
[OK]      Python: Python 3.12.3
[OK]      Dependencies: alle 9 vereiste pakketten zijn aanwezig.
[OK]      Configuratie: de instellingen in .env zijn geldig.
[OFFLINE] Sleutel coinbase: Coinbase niet bereikbaar.
          -> Controleer je internetverbinding. Er is niets mis met de sleutel zelf.
[OK]      Chrome Extension: klaar om te laden.
```

### Veelvoorkomende problemen

**"Python is niet gevonden"**
Python staat er niet, of het vinkje *Add python.exe to PATH* is bij de
installatie vergeten. Installeer Python opnieuw mét dat vinkje.

**"Python is gevonden, maar is te oud"**
Je hebt een versie ouder dan 3.11. Installeer Python 3.12; de oude versie mag
gewoon blijven staan.

**"Installeren van de Python-pakketten is mislukt"**
Bijna altijd geen internet, of een virusscanner die de download blokkeert.
Controleer je verbinding en dubbelklik opnieuw op `install.bat`. Al gelukte
stappen worden overgeslagen.

**"De sleutels zijn afgewezen"**
De sleutel is verlopen of ingetrokken. Maak een nieuwe aan (zie hoofdstuk 2) en
draai `install.bat` opnieuw.

**"OpenAI of Coinbase was niet bereikbaar"**
Een netwerkprobleem, geen sleutelprobleem. Je installatie is niet stuk.
Controleer je internet en probeer het later opnieuw.

**"Het dashboard antwoordde niet binnen 30 seconden"**
Meestal is poort 8000 al bezet door een ander programma. `diagnose.bat` laat
zien welke poorten bezet zijn. Je kunt een andere poort kiezen door in `.env`
de regel `DASHBOARD_PORT=8000` te wijzigen in bijvoorbeeld `DASHBOARD_PORT=8001`.

**"Poort al in gebruik" bij de achtergronddienst**
Zelfde verhaal, maar dan met `JARVIS_CONTROL_PORT=8770` in `.env`. Wijzig je
die, pas dan ook het adres aan in de instellingen van de extensie.

**De extensie zegt "JARVIS draait nu niet op deze pc"**
De achtergronddienst draait niet. Dubbelklik op `start.bat`. Blijft het staan,
kijk dan in `logs\control_service.log`.

**De extensie zegt "Deze aanvraag had geen geldige toegangssleutel"**
De sleutel in de extensie klopt niet meer. Open `state\control_token.txt`,
kopieer de regel opnieuw en plak hem in de instellingen van de extensie.

**Het botvenster is zomaar verdwenen**
Dat kan niet meer gebeuren zonder spoor: kijk in `logs\supervisor.log`. Daar
staat wat er gebeurde, wanneer, en of er herstart is. Staat er
`restart_limit_reached`, dan crashte de bot te vaak achter elkaar en staat in
`logs\loop.log` de oorzaak.

**De bot doet niets**
Dat kan normaal zijn. In papieren modus plaatst hij bewust geen orders, en ook
in live-modus doet hij alleen iets als de strategie een kans ziet. Het
dashboard op <http://127.0.0.1:8000> laat zien wat hij overweegt.

---

## 9. Instellingen

Alle instellingen staan in het bestand **`.env`** in je JARVIS-map. Je kunt het
openen met Kladblok. In **`.env.example`** staat elke instelling met uitleg
erboven.

### Hoef je nooit aan te komen

Alles wat met de strategie, risicogrenzen en veiligheidsschakelaars te maken
heeft. Die staan bewust op de veiligste waarde. Zet ze niet aan omdat het kan.

### Veilig om aan te passen

| Instelling | Wat het doet |
|---|---|
| `DASHBOARD_PORT` | Poort van het dashboard (standaard 8000). |
| `JARVIS_CONTROL_PORT` | Poort van de achtergronddienst (standaard 8770). |
| `JARVIS_RECOVERY_BASE_DELAY` | Eerste wachttijd na een storing, in seconden. |
| `JARVIS_RECOVERY_MAX_DELAY` | Bovengrens voor die wachttijd. |
| `JARVIS_SUPERVISOR_MAX_RESTARTS` | Hoe vaak de bewaker per uur mag herstarten. |
| `LOG_LEVEL` | `INFO` is normaal, `DEBUG` geeft veel meer detail. |

### Levensgevaarlijk zonder begrip van wat je doet

`EXECUTION_MODE`, en alles dat begint met `ENABLE_LIVE_`, `ENABLE_PHASE_`,
`MARKET_ORDER_` of eindigt op `_ACK`. Deze bepalen of er echt geld ingezet
wordt. Lees eerst [`docs/TECHNISCHE-README.md`](docs/TECHNISCHE-README.md).

---

## 10. Verwijderen

JARVIS installeert niets buiten zijn eigen map. Verwijderen gaat zo:

1. Dubbelklik op `stop.bat` en wacht tot er staat dat JARVIS gestopt is.
2. Sluit de twee zwarte vensters als die nog openstaan.
3. Verwijder in Chrome de extensie via `chrome://extensions`.
4. Verwijder de hele JARVIS-map (of gooi hem in de prullenbak).

Dat is alles. Er blijft niets in het Windows-register of in andere mappen achter.

Wil je Python en Node.js ook weg, dan verwijder je die apart via
**Instellingen → Apps**. Let op dat andere programma's ze misschien ook
gebruiken.

> **Belangrijk:** het verwijderen van de map haalt ook je `.env` met je
> API-sleutels weg. Trek die sleutels daarna in bij Coinbase en OpenAI, zodat
> ze niet ergens blijven bestaan.

---

## Alle bestanden om op te dubbelklikken

| Bestand | Wat het doet |
|---|---|
| `install.bat` | Installeren of een bestaande installatie herstellen. |
| `start.bat` | JARVIS starten. |
| `stop.bat` | JARVIS netjes stoppen. |
| `restart.bat` | Stoppen en opnieuw starten. |
| `diagnose.bat` | Alles controleren en een overzicht tonen. |

Elk van deze bestanden blijft bij een fout openstaan met uitleg. Ze sluiten
nooit zonder dat je hebt kunnen lezen wat er aan de hand is.

---

## Voor wie verder wil lezen

- [`docs/TECHNISCHE-README.md`](docs/TECHNISCHE-README.md) — volledige
  technische documentatie: architectuur, alle instellingen, veiligheidslagen.
- [`docs/FAILURES.md`](docs/FAILURES.md) — welke tests bekend rood staan en
  waarom. Bijna allemaal veiligheidspoorten die dicht horen te staan.
- [`INSTALLATIE-WINDOWS.md`](INSTALLATIE-WINDOWS.md) — extra detail over de
  Windows-installatie.
- [`.env.example`](.env.example) — elke instelling met uitleg.
- `docs/` — ontwerpnotities en achtergrond per onderdeel.

---

## Licentie en aansprakelijkheid

Zie [`LICENSE`](LICENSE). Deze software wordt geleverd zonder enige garantie.
Handelen in cryptovaluta brengt een aanzienlijk risico op verlies met zich mee;
gebruik is volledig op eigen risico.
