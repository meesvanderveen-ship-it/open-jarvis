# JARVIS installeren op Windows

Voor wie geen programmeerervaring heeft. Je hoeft geen code te schrijven of
te begrijpen. Volg de stappen op volgorde.

**Tijd:** ongeveer een half uur, waarvan het meeste wachten is.

> **Lees dit eerst.** Deze bot kan met echt geld handelen op Coinbase. Hij
> start altijd in **paper mode**: hij analyseert de echte markt maar plaatst
> geen echte orders. Zo hoort het te blijven tot je precies begrijpt wat je
> doet. Handelen in crypto kan geld kosten. Dit is geen financieel advies.

---

## Wat je nodig hebt

Drie dingen. Regel ze eerst, dan gaat de rest vanzelf.

### 1. Python

Ga naar **https://www.python.org/downloads/** en klik op de grote gele knop.

> **Je hebt Python 3.11 tot en met 3.14 nodig; 3.12 is de aanbevolen versie.**
> De pakketten die de bot gebruikt (numpy, pandas) worden niet voor oudere
> versies uitgebracht. De installatie controleert dit twee keer — één keer
> voordat er iets gebeurt, en één keer met de Python die de pakketten
> daadwerkelijk krijgt — en stopt met een duidelijke melding als je versie
> niet geschikt is.

> **Belangrijk:** zet tijdens het installeren onderin een vinkje bij
> **"Add python.exe to PATH"**. Zonder dat vinkje werkt de installatie niet.
> Zie je dat scherm al voorbij? Verwijder Python en installeer opnieuw.

### 2. Node.js

Ga naar **https://nodejs.org/** en klik op de knop met **LTS** erin.
Klik in de installer steeds op "Next" en daarna "Install".

### 3. Je twee sleutels

Deze hoef je **niet vooraf** te regelen: de installatie opent de officiële
pagina's zelf en pikt de sleutels daarna op. Wil je het toch van tevoren
doen, dan is dit wat er gebeurt.

**OpenAI:** op https://platform.openai.com/api-keys maak je met
"Create new secret key" een sleutel aan en druk je op de kopieerknop. JARVIS
haalt hem van je klembord. OpenAI toont een sleutel maar één keer, dus die
kopieerknop is sowieso de bedoelde handeling.

**Coinbase:** in de CDP Portal maak je een API key aan **van het type
ECDSA**. Je downloadt dan een bestandje dat er zo uitziet:

```json
{
  "name": "organizations/xxxx/apiKeys/xxxx",
  "privateKey": "hele lange tekst"
}
```

Laat dat bestand gewoon in je map Downloads staan. JARVIS ziet de download
verschijnen en leest beide velden er zelf uit; openen of overtypen hoeft
niet.

> Geef de sleutel alleen **View**-rechten zolang je in paper mode test.
> Deel deze twee sleutels met niemand. Wie ze heeft, kan bij je account.

---

## Installeren

1. Pak het projectmapje uit op een plek die je terugvindt, bijvoorbeeld je
   Documenten-map.
2. Open die map en zoek het bestand **`install.bat`** (of het gelijkwaardige
   **`INSTALLEREN-WINDOWS.bat`** — die doen precies hetzelfde).
3. **Dubbelklik erop.**

Er opent een zwart venster met witte tekst. Dat hoort zo. Het installeert
alles vanzelf; dat duurt 5 tot 15 minuten. Het venster loopt negen stappen af
en **sluit nooit vanzelf bij een fout** — er blijft altijd staan wat er misging
en wat je eraan kunt doen.

> Waarschuwt Windows met "Windows heeft uw pc beschermd"? Klik op
> **"Meer informatie"** en daarna op **"Toch uitvoeren"**. Dat komt doordat
> het bestand niet van een bekende uitgever komt.

### Je sleutels koppelen

Aan het eind opent JARVIS de officiële pagina's, één voor één:

| Provider | Wat jij doet |
|---|---|
| OpenAI | key aanmaken, op de **kopieerknop** drukken |
| Coinbase | key van het type **ECDSA** aanmaken en downloaden |

Verder niets. JARVIS haalt de OpenAI-sleutel van je klembord en ziet het
Coinbase-bestand in Downloads verschijnen. Daarna slaat hij ze op en
controleert hij meteen of ze echt werken.

> Lukt het oppikken niet — bijvoorbeeld omdat het bestand er al stond — dan
> krijg je alsnog gewoon een lijstje met gevonden bestanden en kies je een
> nummer.

Wil je de waarden liever met de hand invoeren, dan kan dat nog steeds:

```
.venv\Scripts\python -m tools.setup_wizard
```

> **Bij het invoeren van een secret zie je sterretjes.** Dat is expres, zodat
> niemand kan meelezen.

Een sleutel later vervangen:

```
.venv\Scripts\python -m tools.connect_services --reconnect coinbase
```

Aan het eind staat er:

```
INSTALLATIE GELUKT
```

Staat er iets anders? Dan meldt het venster precies wat er mist. Dubbelklik
het installatiebestand opnieuw en verbeter dat ene onderdeel.

---

## Starten

Dubbelklik op **`start.bat`** (of `START-JARVIS.bat`).

Er gebeurt dit:

1. Je sleutels worden gecontroleerd — alleen leesvragen, er wordt niets
   gekocht of verkocht.
2. De systeemcontrole draait: Python, pakketten, configuratie, sleutels,
   handelsmotor, dashboard en extensie.
3. Twee zwarte vensters openen: het dashboard en de achtergronddienst voor de
   Chrome-extensie.
4. De bot zelf start onder een **bewaker**. Crasht hij door een storing, dan
   wordt hij vanzelf opnieuw gestart met een oplopende wachttijd. Bij een
   configuratiefout stopt de bewaker juist meteen en legt uit wat er mis is —
   opnieuw proberen zou dat toch niet oplossen.
5. Je browser opent vanzelf op **http://127.0.0.1:8000**.

**Laat die twee zwarte vensters open staan.** Ze sluiten betekent dat het
dashboard en de extensie-dienst stoppen.

Bovenaan het dashboard zie je meteen hoe het ervoor staat:

| Wat je ziet | Wat het betekent |
|---|---|
| **JARVIS READY** (groen) | Alles klopt, de bot draait |
| **SETUP REQUIRED** (oranje) | Er ontbreekt een sleutel |
| **CONFIGURATION ERROR** (rood) | Een sleutel klopt niet — er staat precies welke |

Bij oranje of rood staat er altijd bij wát er mis is. Dubbelklik dan
`INSTALLEREN-WINDOWS.bat` om het te herstellen.

## Stoppen

Dubbelklik op **`stop.bat`**.

Dat is de juiste manier: de bot krijgt een *net* stopverzoek en mag een lopende
handelscyclus afmaken. Dat kan een halve minuut duren — dat hoort zo. De
vensters gewoon wegklikken zou de bot midden in een handeling kunnen afbreken.

**Herstarten** doe je met `restart.bat`. Die stopt eerst en start pas daarna,
en weigert te starten als het stoppen niet gelukt is — twee bots die dezelfde
posities beheren is het laatste wat je wilt.

---

## De Chrome-extensie

Wil je JARVIS vanuit je browser bedienen in plaats van met zwarte vensters:

1. Open Chrome en ga naar `chrome://extensions`
2. Zet rechtsboven **Ontwikkelaarsmodus** aan.
3. Klik op **Uitgepakte extensie laden** en kies de map **`extension`**.
4. Klik op het JARVIS-icoontje, dan op **Instellingen**.
5. Open `state\control_token.txt` met Kladblok, kopieer de regel en plak hem
   in het veld *Toegangssleutel*. Klik op **Opslaan** en **Verbinding testen**.

Je kunt dan starten, stoppen, herstarten, de systeemcontrole bekijken en de
laatste logregels lezen. Je API-sleutels zitten **niet** in de extensie; die
blijven in het programma op je pc.

---

## Werkt er iets niet?

Dubbelklik op **`diagnose.bat`**. Die controleert Windows, Python, de
pakketten, je configuratie, de draaiende processen, de poorten en draait een
zelftest. Je krijgt per onderdeel `[OK]`, `[LET OP]`, `[OFFLINE]` of `[FOUT]`
te zien, met erbij wat je eraan kunt doen.

---

## Controleren of je sleutels echt werken

De controle bij het starten kijkt alleen of je sleutels de juiste *vorm*
hebben. Wil je weten of OpenAI en Coinbase ze ook echt accepteren, dan is er
een extra controle die één onschuldige vraag aan beide diensten stelt. Er
wordt niets gekocht of verkocht.

1. Open de projectmap.
2. Klik in de adresbalk bovenin, typ `cmd` en druk op Enter.
3. Plak dit en druk op Enter:

```
.venv\Scripts\python -m tools.setup_wizard --check --online
```

Je krijgt per dienst te zien of het gelukt is.

---

## Als er iets misgaat

| Wat je ziet | Wat je doet |
|---|---|
| "Python is niet gevonden" | Python opnieuw installeren, mét het vinkje bij "Add python.exe to PATH" |
| "Node.js is niet gevonden" | Node.js installeren via nodejs.org, knop met LTS |
| Het venster sluit meteen | Dat hoort niet te kunnen: elk venster pauzeert bij een fout. Gebeurt het toch, draai dan `diagnose.bat` |
| "SETUP REQUIRED" | Een sleutel ontbreekt. Draai het installatiebestand opnieuw |
| "CONFIGURATION ERROR" | Een sleutel is onbruikbaar. Het scherm noemt welke; haal hem opnieuw op |
| "niet bereikbaar" bij de sleutelcontrole | Een netwerkprobleem, **geen** sleutelprobleem. Je installatie is niet stuk; probeer het later opnieuw |
| Browser zegt "kan geen verbinding maken" | Wacht 10 seconden en ververs. Het dashboardvenster moet openstaan |
| "poort al in gebruik" | Een ander programma bezet poort 8000 of 8770. `diagnose.bat` laat zien welke. Wijzig `DASHBOARD_PORT` of `JARVIS_CONTROL_PORT` in `.env` |
| Coinbase-sleutel wordt afgewezen | Controleer of je hem niet half hebt gekopieerd. De `privateKey` is één lange regel |
| Het botvenster is verdwenen | Kijk in `logs\supervisor.log`. Daar staat wat er gebeurde en of er herstart is |
| Extensie zegt "JARVIS draait nu niet op deze pc" | De achtergronddienst draait niet. Dubbelklik op `start.bat` |

---

## Waar je spullen staan

| Bestand | Wat het is |
|---|---|
| `.env` | Je sleutels. **Nooit delen, nooit doorsturen.** |
| `logs\loop.log` | Wat de bot heeft gedaan |
| `logs\supervisor.log` | Wat de bewaker deed: starten, crashes, wachttijden |
| `logs\control_service.log` | De achtergronddienst voor de extensie |
| `state\control_token.txt` | Toegangssleutel voor de Chrome-extensie |
| `reports\` | Rapporten van de bot |

Je sleutels worden alleen op je eigen computer bewaard, in `.env`. Ze worden
nergens naartoe gestuurd, niet in logbestanden geschreven en niet in het
dashboard getoond.

---

## Over paper mode en echt geld

De bot staat op `EXECUTION_MODE=paper`. Hij analyseert de echte markt en
doorloopt alle beslissingen, maar stuurt **geen** orders naar Coinbase.

Live gaan is een aparte, bewuste beslissing waarbij je meerdere
veiligheidsschakelaars één voor één moet omzetten. Dat staat beschreven in
`docs\TECHNISCHE-README.md` en in de map `docs\`. Doe dat pas als je begrijpt
wat elke schakelaar doet. Zolang `EXECUTION_MODE=paper` staat, kan er niets
misgaan met echt geld.
