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

> **Je hebt Python 3.12 of nieuwer nodig.** De pakketten die de bot gebruikt
> (numpy, pandas) worden niet meer voor oudere versies uitgebracht. De
> installatie controleert dit en stopt met een duidelijke melding als je
> versie te oud is.

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
2. Open die map en zoek het bestand **`INSTALLEREN-WINDOWS.bat`**.
3. **Dubbelklik erop.**

Er opent een zwart venster met witte tekst. Dat hoort zo. Het installeert
alles vanzelf; dat duurt 5 tot 10 minuten.

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

Dubbelklik op **`START-JARVIS.bat`**.

Er gebeurt dit:

1. Je sleutels worden gecontroleerd.
2. Twee zwarte vensters openen: één voor de bot, één voor het dashboard.
3. Je browser opent vanzelf op **http://127.0.0.1:8000**.

**Laat die twee zwarte vensters open staan.** Ze sluiten betekent dat JARVIS
stopt.

Bovenaan het dashboard zie je meteen hoe het ervoor staat:

| Wat je ziet | Wat het betekent |
|---|---|
| **JARVIS READY** (groen) | Alles klopt, de bot draait |
| **SETUP REQUIRED** (oranje) | Er ontbreekt een sleutel |
| **CONFIGURATION ERROR** (rood) | Een sleutel klopt niet — er staat precies welke |

Bij oranje of rood staat er altijd bij wát er mis is. Dubbelklik dan
`INSTALLEREN-WINDOWS.bat` om het te herstellen.

## Stoppen

Sluit de twee zwarte vensters. Of klik erin en druk op **Ctrl + C**.

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
| Het venster sluit meteen | Rechtermuisklik op het bestand → "Bewerken" is *niet* nodig; dubbelklik gewoon opnieuw en lees de laatste regels |
| "SETUP REQUIRED" | Een sleutel ontbreekt. Draai het installatiebestand opnieuw |
| "CONFIGURATION ERROR" | Een sleutel is onbruikbaar. Het scherm noemt welke; haal hem opnieuw op |
| Browser zegt "kan geen verbinding maken" | Wacht 10 seconden en ververs. Het dashboardvenster moet openstaan |
| Coinbase-sleutel wordt afgewezen | Controleer of je hem niet half hebt gekopieerd. De `privateKey` is één lange regel |

---

## Waar je spullen staan

| Bestand | Wat het is |
|---|---|
| `.env` | Je sleutels. **Nooit delen, nooit doorsturen.** |
| `logs\` | Wat de bot heeft gedaan |
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
`README.md` en in de map `docs\`. Doe dat pas als je begrijpt wat elke
schakelaar doet. Zolang `EXECUTION_MODE=paper` staat, kan er niets misgaan
met echt geld.
