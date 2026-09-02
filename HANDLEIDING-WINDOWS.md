# BEGIN HIER — JARVIS installeren op Windows

Deze handleiding is geschreven voor iemand die niets van programmeren weet.
Je hoeft geen code te lezen, te schrijven of te begrijpen. Volg de stappen op
volgorde en lees de zwarte vensters die verschijnen — daar staat altijd in
gewone taal wat er gebeurt.

**Tijd:** ongeveer 20 tot 30 minuten, waarvan het meeste wachten is.

---

## Inhoud

| | |
|---|---|
| [1. Wat is JARVIS?](#1-wat-is-jarvis) | [11. Waar vind ik logs?](#11-waar-vind-ik-logs) |
| [2. Wat heb ik nodig?](#2-wat-heb-ik-nodig) | [12. Hoe weet ik of JARVIS draait?](#12-hoe-weet-ik-of-jarvis-draait) |
| [3. Installeren](#3-installeren) | [13. Poort bezet](#13-poort-bezet) |
| [4. API-sleutels instellen](#4-api-sleutels-instellen) | [14. API-sleutel werkt niet](#14-api-sleutel-werkt-niet) |
| [5. API-validatie](#5-api-validatie) | [15. De bot start niet](#15-de-bot-start-niet) |
| [6. JARVIS starten](#6-jarvis-starten) | [16. Herstel na een storing](#16-herstel-na-een-storing) |
| [7. JARVIS stoppen](#7-jarvis-stoppen) | [17. Veiligheidsmodus](#17-veiligheidsmodus) |
| [8. Opnieuw starten](#8-opnieuw-starten) | [18. Data en configuratie](#18-data-en-configuratie) |
| [9. Problemen controleren](#9-problemen-controleren) | [19. Opnieuw installeren](#19-opnieuw-installeren) |
| [10. Chrome-extensie](#10-chrome-extensie) | [20. Volledig verwijderen](#20-volledig-verwijderen) |

Loopt er iets mis? Kijk in **[PROBLEMEN-OPLOSSEN.md](PROBLEMEN-OPLOSSEN.md)**.

---

## 1. Wat is JARVIS?

JARVIS is een handelsprogramma voor cryptovaluta dat op **jouw eigen computer**
draait. Het kijkt naar de markt op Coinbase, laat een reeks AI-modellen
meedenken over wat een verstandige zet zou zijn, en legt die gedachtegang langs
een aparte veiligheidslaag die het laatste woord heeft.

Belangrijk om te begrijpen:

- **De AI mag alleen voorstellen doen.** Of er echt iets naar Coinbase gaat,
  bepaalt een aparte laag met vaste regels — geen AI.
- **JARVIS draait standaard in papieren modus.** Hij denkt volledig mee en
  houdt bij wat hij zóu doen, maar stuurt niets naar Coinbase. Er wordt dus
  geen geld ingezet zolang je dat niet zelf bewust aanzet.
- **Alles blijft op je eigen pc.** Je sleutels, je logboeken, je instellingen.

> ### ⚠️ Lees dit voordat je verder gaat
>
> Deze software kán echte orders plaatsen met echt geld, als je die schakelaars
> later zelf omzet. Handelen in cryptovaluta brengt een aanzienlijk risico op
> verlies met zich mee. Dit is **geen financieel advies** en er is **geen
> enkele garantie**. Gebruik is volledig op eigen risico.
>
> Laat JARVIS eerst een tijd in papieren modus meelopen voordat je ook maar
> overweegt iets aan te zetten.

---

## 2. Wat heb ik nodig?

| Wat | Waarom | Verplicht? |
|---|---|---|
| **Windows 10 of 11** | JARVIS wordt hiervoor geleverd | Ja |
| **Internetverbinding** | Om de markt te volgen en de installatie te doen | Ja |
| **Een Coinbase-account** | Om marktgegevens op te halen | Ja |
| **Een OpenAI-account** | Hier draait het denkwerk op. Dit kost geld per gebruik | Ja |
| **Google Chrome** | Alleen voor de extensie, die is optioneel | Nee |
| **Ongeveer 2 GB vrije schijfruimte** | Voor de onderdelen die geïnstalleerd worden | Ja |

**Python en Node.js hoef je niet vooraf te installeren.** De installatie
controleert of ze er zijn. Zijn ze er niet, dan krijg je een scherm dat precies
vertelt wat je moet downloaden en waar. Node.js kan de installatie er in veel
gevallen zelf bij zetten.

> **Over de kosten:** Coinbase rekent niets voor het meelezen van marktgegevens.
> OpenAI rekent wél af per gebruik. Zet een uitgavenlimiet in je OpenAI-account
> voordat je JARVIS laat draaien.

---

## 3. Installeren

### Stap 1 — Uitpakken

1. Je hebt een ZIP-bestand gedownload.
2. Klik er met de **rechtermuisknop** op en kies **Alles uitpakken…**
3. Kies een plek die je terugvindt, bijvoorbeeld je map **Documenten**.
4. Klik op **Uitpakken**.

> Pak het bestand echt uit. Als je in het ZIP-bestand blijft "kijken" zonder
> uit te pakken, werkt de installatie niet.

### Stap 2 — De installatie starten

1. Open de map die uit het ZIP-bestand kwam.
2. Zoek het bestand **`install.bat`**.
3. **Dubbelklik erop.**

Er opent een zwart venster met witte tekst. Dat hoort zo. Laat het openstaan.

> **Waarschuwt Windows met "Windows heeft uw pc beschermd"?**
> Klik op **Meer informatie** en daarna op **Toch uitvoeren**. Die melding komt
> doordat het bestand niet van een bekende uitgever komt — niet doordat er iets
> mis is.

### Stap 3 — Meekijken

Het venster loopt negen stappen af:

```
[1/9] Python controleren
[2/9] Node.js en npm controleren
[3/9] Python-omgeving klaarzetten
[4/9] Python-pakketten installeren        <- dit duurt het langst
[5/9] Dashboard bouwen
[6/9] Je API-sleutels instellen           <- hier moet jij iets doen
[7/9] Sleutels controleren bij OpenAI en Coinbase
[8/9] Zelftest van de installatie
[9/9] Chrome-extensie voorbereiden
```

**Het venster sluit nooit vanzelf als er iets misgaat.** Loopt een stap vast,
dan blijft het openstaan met een uitleg in gewone taal, en met wat je eraan kunt
doen. Je kunt de installatie daarna gewoon opnieuw starten; stappen die al
gelukt zijn, worden overgeslagen.

### Als Python ontbreekt

De installatie stopt met een uitleg. Doe dan dit:

1. Ga naar <https://www.python.org/downloads/>
2. Download **Python 3.12**.
3. **Belangrijk:** zet tijdens het installeren onderin een vinkje bij
   **"Add python.exe to PATH"** vóórdat je op *Install* klikt.
4. Sluit het zwarte venster en dubbelklik opnieuw op `install.bat`.

Python 3.11 tot en met 3.14 werkt ook. Ouder dan 3.11 werkt niet.

### Als Node.js ontbreekt

De installatie biedt aan het zelf te installeren. Typ **J** en druk op Enter.
Lukt dat niet, dan krijg je de instructie om het zelf te doen via
<https://nodejs.org/> — klik daar op de knop met **LTS** erin.

---

## 4. API-sleutels instellen

Een API-sleutel is een lang, geheim wachtwoord waarmee JARVIS namens jou
gegevens mag opvragen. **Je maakt ze zelf aan.** Niemand anders kan of mag dat
voor je doen, en JARVIS maakt ze nooit automatisch aan.

Bij stap 6 opent JARVIS de officiële pagina's voor je. Je hoeft niets op te
zoeken.

### Coinbase

1. De pagina <https://portal.cdp.coinbase.com/access/api> gaat open.
2. Log in en klik op **Create API key**.
3. Kies sleuteltype **ECDSA**.
4. Geef alleen de rechten die je nodig hebt. Voor meelezen is **View** genoeg.
   Pas als je later echt wilt laten handelen is **Trade** nodig.
5. Download het JSON-bestand dat Coinbase je aanbiedt.

JARVIS ziet die download vanzelf verschijnen en leest hem uit. Je hoeft het
bestand niet te openen of over te typen.

### OpenAI

1. De pagina <https://platform.openai.com/api-keys> gaat open.
2. Klik op **Create new secret key**.
3. Klik op de **kopieerknop**.

JARVIS haalt hem van je klembord. OpenAI laat een sleutel maar één keer zien,
dus die kopieerknop is sowieso de bedoelde handeling.

### Lukt het oppikken niet?

Dan wordt er gewoon om gevraagd, of krijg je een lijstje met gevonden bestanden
waaruit je een nummer kiest. Bij het intypen van een geheime waarde zie je
sterretjes — dat is expres, zodat niemand kan meelezen.

### Waar komen die sleutels terecht?

In een bestand met de naam **`.env`** in je JARVIS-map, alleen op jouw pc.
In dat bestand staat het er ongeveer zo uit te zien:

```
OPENAI_API_KEY=JOUW_OPENAI_KEY
COINBASE_API_KEY=JOUW_COINBASE_KEY
COINBASE_API_SECRET=JOUW_COINBASE_SECRET
```

- Ze gaan **nooit** ergens anders heen dan naar Coinbase en OpenAI zelf.
- Ze komen **nooit** in een logboek, foutmelding of scherm terecht. Overal waar
  iets van een sleutel zichtbaar zou kunnen worden, staat `[REDACTED]`.
- Vraagt iemand je ooit om je sleutel in een chat te plakken: **doe dat niet.**

---

## 5. API-validatie

Een sleutel kan er perfect uitzien en toch niet werken — bijvoorbeeld omdat je
hem later hebt ingetrokken. JARVIS doet daarom een echte **leesvraag** aan
beide leveranciers. Er wordt daarbij niets gekocht of verkocht.

Je kunt vier uitkomsten te zien krijgen. Ze betekenen iets heel verschillends:

| Wat je ziet | Wat het betekent | Wat je doet |
|---|---|---|
| **READY** | Alles klopt. De leverancier accepteert je sleutel. | Niets. Klaar. |
| **SETUP_REQUIRED** | Er is nog helemaal geen sleutel ingesteld. Dit is normaal vóór stap 6. | Doorloop stap 6 van de installatie. |
| **CONFIGURATION_ERROR** | De leverancier is bereikbaar maar wéigert je sleutel: verlopen, ingetrokken, of te weinig rechten. | Maak een nieuwe sleutel aan (zie hoofdstuk 4). |
| **VERIFICATION_UNAVAILABLE** | Er kon geen contact gelegd worden. Internet eruit, storing bij de leverancier, of een firewall. | Controleer je internet en probeer het later opnieuw. **Er is niets mis met je sleutel.** |

**Dit onderscheid is belangrijk.** JARVIS zal een netwerkprobleem nooit
presenteren als een verkeerde sleutel. Zie je `VERIFICATION_UNAVAILABLE`, ga dan
géén nieuwe sleutels aanmaken — er is niets stuk.

---

## 6. JARVIS starten

**Dubbelklik op `start.bat`.**

Er gebeurt dit:

1. Je sleutels worden gecontroleerd (weer alleen leesvragen).
2. De systeemcontrole loopt: Python, pakketten, configuratie, sleutels,
   handelsmotor, dashboard, extensie.
3. Er openen **twee zwarte vensters**: het dashboard en de achtergronddienst.
   **Laat die openstaan.** Sluiten betekent stoppen.
4. De bot zelf start onder een bewaker (zie hoofdstuk 16).
5. Je browser opent vanzelf op **<http://127.0.0.1:8000>**.

Ontbreekt er iets belangrijks, dan start JARVIS niet en vertelt het scherm wat
er mist. Dat is met opzet: liever niet starten dan draaien terwijl er iets stuk
is.

---

## 7. JARVIS stoppen

**Dubbelklik op `stop.bat`.**

De bot krijgt een **net** stopverzoek en mag een lopende handelscyclus afmaken.
Dat kan een halve minuut duren — dat hoort zo. Halverwege afbreken zou een
halve orderadministratie kunnen achterlaten.

> **Klik de zwarte vensters niet zomaar weg** om te stoppen. Gebruik `stop.bat`.
> Blijft het lang duren, wacht dan een minuut en probeer het nog een keer; het
> stopverzoek blijft staan.

---

## 8. Opnieuw starten

**Dubbelklik op `restart.bat`.**

Die stopt eerst en start daarna pas. Lukt het stoppen niet, dan start hij
**niet** opnieuw op — twee bots die dezelfde posities beheren is het laatste
wat je wilt.

---

## 9. Problemen controleren

**Dubbelklik op `diagnose.bat`.**

Die controleert je hele installatie en verandert niets. Je krijgt per onderdeel
te zien hoe het ervoor staat:

```
[OK]      Python: Python 3.12.3
[OK]      Dependencies: alle 9 vereiste pakketten zijn aanwezig.
[OK]      Configuratie: de instellingen in .env zijn geldig.
[OFFLINE] Sleutel coinbase: Coinbase niet bereikbaar.
          -> Controleer je internetverbinding. Er is niets mis met de sleutel zelf.
[OK]      Chrome Extension: klaar om te laden.
```

De vier tekens betekenen:

| | |
|---|---|
| `[OK]` | Dit onderdeel is in orde. |
| `[LET OP]` | Bruikbaar, maar kijk er even naar. |
| `[OFFLINE]` | Niet te controleren — meestal een netwerkprobleem, geen defect. |
| `[FOUT]` | Kapot of ontbrekend. JARVIS start hier niet mee. |

---

## 10. Chrome-extensie

Met de extensie bedien je JARVIS vanuit je browser, zonder zwarte vensters.
Dit is **optioneel**; zonder extensie werkt alles gewoon.

### Installeren

1. Open Chrome en ga naar **`chrome://extensions`**
2. Zet rechtsboven **Ontwikkelaarsmodus** aan.
3. Klik op **Uitgepakte extensie laden**.
4. Kies de map **`extension`** in je JARVIS-map en klik op **Map selecteren**.
5. Klik op het JARVIS-icoontje in de werkbalk, en dan op **Instellingen**.
6. Open met **Kladblok** het bestand **`state\control_token.txt`** in je
   JARVIS-map. Kopieer de regel die erin staat.
7. Plak hem in het veld **Toegangssleutel** en klik op **Opslaan**.
8. Klik op **Verbinding testen**. Je hoort nu te lezen: *"Verbonden."*

### Wat kun je ermee?

- Zien of JARVIS draait, opstart, herstelt van een storing of gestopt is.
- Starten, stoppen en herstarten.
- De volledige systeemcontrole bekijken.
- De laatste honderd logregels lezen.
- Je API-sleutels controleren (alleen leesvragen).

Het icoontje in de werkbalk toont de toestand: **AAN** (groen), **WACHT**
(oranje — herstelt van een storing), **UIT** (grijs), **!** (rood — gestopt
door een fout) of **?** (de achtergronddienst draait niet).

### Waarom die toegangssleutel?

De extensie praat met een klein programma op je eigen pc. Zonder sleutel zou
elke website die je opent dat programma kunnen aanspreken en je bot kunnen
stoppen of starten. De sleutel voorkomt dat.

Die sleutel geldt **alleen op jouw pc** en geeft **geen toegang tot je geld** —
dat kan hij niet, want je Coinbase-sleutel zit er niet in en verlaat je
JARVIS-map nooit. Deel hem toch met niemand.

---

## 11. Waar vind ik logs?

Alle logboeken staan in de map **`logs`** in je JARVIS-map. Je kunt ze openen
met Kladblok.

| Bestand | Wat erin staat |
|---|---|
| `logs\loop.log` | Wat de bot doet: elke cyclus, elke beslissing, elke fout. |
| `logs\supervisor.log` | Wat de bewaker doet: starten, crashes, wachttijden. |
| `logs\control_service.log` | De achtergronddienst voor de extensie. |
| `logs\loop_errors.jsonl` | Alleen de fouten, met per fout of hij tijdelijk was. |

**Er staan nooit sleutels in.** Alles wat op een sleutel lijkt, wordt vervangen
door `[REDACTED]` voordat het opgeschreven wordt.

Snel de laatste regels bekijken kan ook via de Chrome-extensie, onder
*Laatste logregels*.

---

## 12. Hoe weet ik of JARVIS draait?

Vier manieren, van makkelijk naar precies:

1. **Staan er twee zwarte vensters open?** Zo ja, dan draaien het dashboard en
   de achtergronddienst.
2. **Open <http://127.0.0.1:8000> in je browser.** Krijg je het dashboard te
   zien, dan draait het dashboard.
3. **Kijk naar het icoontje van de Chrome-extensie.** Groen met **AAN**
   betekent dat de bot draait.
4. **Dubbelklik op `diagnose.bat`.** Onder *Draaiende processen* staat het
   exacte antwoord.

> Een venster dat openstaat betekent niet automatisch dat de bot zelf draait.
> De bot draait onder een bewaker, in een eigen proces. `diagnose.bat` en de
> extensie geven het echte antwoord.

---

## 13. Poort bezet

Een "poort" is een nummer waarop een programma bereikbaar is. JARVIS gebruikt
er twee: **8000** voor het dashboard en **8770** voor de achtergronddienst.

Krijg je een melding dat een poort bezet is, dan betekent dat bijna altijd één
van twee dingen:

1. **JARVIS draait al.** Kijk of er nog een zwart venster openstaat. Stop hem
   met `stop.bat` en start opnieuw.
2. **Een ander programma gebruikt die poort.** Dat kan.

In het tweede geval kies je een ander nummer. Open het bestand **`.env`** met
Kladblok en pas de betreffende regel aan:

```
DASHBOARD_PORT=8001
JARVIS_CONTROL_PORT=8771
```

Wijzig je `JARVIS_CONTROL_PORT`, pas dan ook het adres aan in de instellingen
van de Chrome-extensie.

`diagnose.bat` laat onder *Poorten* zien welke bezet zijn.

---

## 14. API-sleutel werkt niet

Kijk eerst wélke melding je krijgt — dat bepaalt wat je moet doen:

| Melding | Wat er aan de hand is | Wat je doet |
|---|---|---|
| `CONFIGURATION_ERROR` of "afgewezen" | De leverancier weigert de sleutel actief | Maak een nieuwe aan |
| `VERIFICATION_UNAVAILABLE` of "niet bereikbaar" | Er was geen contact mogelijk | Wacht en probeer opnieuw. **Maak geen nieuwe sleutel aan** |
| `SETUP_REQUIRED` of "ontbreekt" | Er staat nog geen sleutel | Doorloop stap 6 van de installatie |

Wordt je sleutel **afgewezen**, dan zijn dit de gebruikelijke oorzaken:

- De sleutel is bij de leverancier ingetrokken of verlopen.
- Bij Coinbase is een ander sleuteltype gekozen dan **ECDSA**.
- De sleutel is maar half gekopieerd. Bij Coinbase is de `privateKey` één lange
  regel; er mag niets ontbreken.
- De sleutel heeft te weinig rechten voor wat je wilt doen.
- Bij OpenAI: er staat geen tegoed of betaalmethode op je account.

Een sleutel opnieuw koppelen kan zo:

1. Open de JARVIS-map.
2. Klik bovenin in de adresbalk, typ `cmd` en druk op Enter.
3. Plak dit en druk op Enter:

```
.venv\Scripts\python -m tools.connect_services --reconnect coinbase
```

Voor OpenAI vervang je `coinbase` door `openai`.

> **Zet nooit je sleutel in een bericht, e-mail of schermafdruk.** Ook niet om
> hulp te vragen. Niemand heeft hem nodig om je te helpen.

---

## 15. De bot start niet

Werk deze volgorde af. Stop zodra je de oorzaak gevonden hebt.

1. **Dubbelklik op `diagnose.bat`.** In negen van de tien gevallen staat het
   antwoord daar al, met de oplossing erbij.
2. **Staat er `[FOUT]` bij Configuratie?** Dan ontbreekt `.env`. Draai
   `install.bat` opnieuw.
3. **Staat er `[FOUT]` bij een sleutel?** Ga naar hoofdstuk 14.
4. **Staat er `[FOUT]` bij Dependencies?** Draai `install.bat` opnieuw; meestal
   is de installatie halverwege afgebroken.
5. **Meldt hij een bezette poort?** Ga naar hoofdstuk 13.
6. **Staat alles op `[OK]` maar start hij toch niet?** Open
   `logs\supervisor.log` met Kladblok en lees de laatste regels. Daar staat wat
   er gebeurde.
7. **Staat er `restart_limit_reached` in dat logboek?** Dan is de bot te vaak
   achter elkaar omgevallen. De oorzaak staat in `logs\loop.log`.

---

## 16. Herstel na een storing

De bot draait niet los, maar onder een **bewaker**. Valt de bot om door een
storing — het internet hapert, Coinbase is even niet bereikbaar — dan gebeurt
dit vanzelf:

```
crash  ->  in het logboek zetten  ->  netjes opruimen
       ->  even wachten  ->  opnieuw starten  ->  in de gaten houden
```

De wachttijd loopt op: 5, dan 10, dan 20, dan 40 seconden. Dat is met opzet.
Een leverancier die plat ligt moet niet elke seconde opnieuw bestookt worden.

**Maar niet elke fout wordt opnieuw geprobeerd.** Bij een fout die zichzelf
niet oplost — een ontbrekende sleutel, een verkeerde instelling — stopt de
bewaker meteen en legt uit wat je moet doen. Opnieuw starten zou daar toch
niets aan veranderen.

En crasht de bot meer dan **tien keer binnen een uur**, dan houdt de bewaker
ermee op en verwijst naar het logboek. Zo kan er nooit een eindeloze
herstartlus ontstaan die je computer bezet houdt.

---

## 17. Veiligheidsmodus

**Een verse installatie plaatst geen enkele order.**

Dat is geen belofte maar een instelling: in `.env` staat elke schakelaar voor
live handelen op `false`, en `EXECUTION_MODE` staat op `paper`. JARVIS
analyseert de echte markt, doorloopt alle beslissingen en schrijft op wat hij
zóu doen — maar er gaat niets naar Coinbase.

Dat geldt ook voor:

- de installatie zelf
- het starten en herstarten
- de sleutelcontrole (dat zijn alleen leesvragen)
- alle tests

Live gaan is een aparte, bewuste beslissing waarbij je meerdere
veiligheidsschakelaars één voor één moet omzetten. Dat staat beschreven in
[`docs/TECHNISCHE-README.md`](docs/TECHNISCHE-README.md). Doe dat pas als je
begrijpt wat elke schakelaar doet.

> Zolang `EXECUTION_MODE=paper` staat, kan er niets misgaan met echt geld.

---

## 18. Data en configuratie

Deze bestanden en mappen zijn van jou. **Verwijder ze niet zomaar:**

| Bestand of map | Wat het is | Wat je kwijtraakt |
|---|---|---|
| `.env` | Je API-sleutels en instellingen | Je moet alles opnieuw koppelen |
| `state\` | Wat JARVIS bijhoudt: posities, orders, voortgang | De administratie van je bot |
| `logs\` | De logboeken | Je geschiedenis en de mogelijkheid om iets uit te zoeken |
| `reports\` | Rapporten die JARVIS gemaakt heeft | Je analyses |

Deze mogen wél weg — ze worden opnieuw aangemaakt:

| Map | Wat het is |
|---|---|
| `.venv\` | De geïnstalleerde Python-onderdelen |
| `dashboard\frontend\node_modules\` | De onderdelen van de webpagina |
| `dashboard\frontend\dist\` | De gebouwde webpagina |
| `__pycache__\` | Tijdelijke bestanden |

---

## 19. Opnieuw installeren

Wil je opnieuw installeren zonder je gegevens kwijt te raken:

1. Dubbelklik op **`stop.bat`** en wacht tot er staat dat JARVIS gestopt is.
2. Dubbelklik op **`install.bat`**.

Meer is het niet. De installatie:

- laat je bestaande `.env` staan en vult alleen aan wat ontbreekt;
- laat `state\`, `logs\` en `reports\` volledig met rust;
- slaat stappen over die al gelukt zijn.

Wil je met een schone lei beginnen maar je sleutels houden, verwijder dan
alleen de map `.venv` en draai `install.bat` opnieuw.

> Maak vóór een grote wijziging een kopie van `.env` en de map `state`. Plak ze
> ergens anders neer. Dan kun je altijd terug.

---

## 20. Volledig verwijderen

> ### ⚠️ Lees dit eerst
>
> Hierna is alles weg: je instellingen, je logboeken en de administratie van je
> bot. **Dit kan niet ongedaan gemaakt worden.** Wil je iets bewaren, kopieer
> dan eerst `.env`, `state\` en `logs\` naar een andere map.

1. Dubbelklik op **`stop.bat`** en wacht tot er staat dat JARVIS gestopt is.
2. Sluit de twee zwarte vensters als die nog openstaan.
3. Heb je de extensie geïnstalleerd: ga in Chrome naar `chrome://extensions` en
   klik bij JARVIS op **Verwijderen**.
4. Verwijder de hele JARVIS-map, of sleep hem naar de prullenbak.

Dat is alles. JARVIS installeert niets buiten zijn eigen map: er blijft niets
achter in het Windows-register of in andere mappen.

**Trek daarna je sleutels in** bij Coinbase en OpenAI, zodat ze niet ergens
blijven bestaan.

Wil je Python en Node.js ook weg, dan verwijder je die apart via
**Instellingen → Apps**. Let op dat andere programma's ze misschien ook
gebruiken.

---

## Alle bestanden om op te dubbelklikken

| Bestand | Wat het doet |
|---|---|
| `install.bat` | Installeren, of een bestaande installatie herstellen |
| `start.bat` | JARVIS starten |
| `stop.bat` | JARVIS netjes stoppen |
| `restart.bat` | Stoppen en opnieuw starten |
| `diagnose.bat` | Alles controleren en een overzicht tonen |

Elk van deze blijft bij een fout openstaan met uitleg. Ze sluiten nooit zonder
dat je hebt kunnen lezen wat er aan de hand is.

---

## Verder lezen

- **[PROBLEMEN-OPLOSSEN.md](PROBLEMEN-OPLOSSEN.md)** — tabel met problemen,
  oorzaken en oplossingen
- **[README.md](README.md)** — kort overzicht
- **[docs/TECHNISCHE-README.md](docs/TECHNISCHE-README.md)** — voor
  programmeurs: architectuur, alle instellingen, de veiligheidslagen
- **[.env.example](.env.example)** — elke instelling met uitleg erboven
