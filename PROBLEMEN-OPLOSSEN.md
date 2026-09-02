# Problemen oplossen

Dit is de foutenzoeker van JARVIS. Zoek links in de tabel de zin op die jij op
je scherm ziet, en volg de oplossing in de rechterkolom.

> **Werkt het na drie pogingen nog steeds niet?** Dubbelklik op
> `diagnose.bat`. Dat programma controleert alles op je pc en zegt in gewone
> taal wat er mis is. Het verandert niets — het kijkt alleen.

> **Belangrijk:** geen enkele oplossing hieronder wist je handelsgegevens of je
> instellingen. Waar dat wel zou kunnen (opnieuw installeren, verwijderen)
> staat het er nadrukkelijk bij.

---

## Snel naar het juiste stuk

| Waar gaat het mis? | Ga naar |
|---|---|
| Tijdens `install.bat` | [Installatie](#installatie) |
| Bij het starten | [Starten en stoppen](#starten-en-stoppen) |
| Met de API-sleutels | [API-sleutels](#api-sleutels) |
| De bot draait, maar stopt of doet niets | [De bot draait niet stabiel](#de-bot-draait-niet-stabiel) |
| In Chrome | [Chrome-extensie](#chrome-extensie) |

---

## Installatie

| Probleem | Mogelijke oorzaak | Oplossing |
|---|---|---|
| **`Python is niet gevonden.`** | Python staat niet op deze pc, of is geïnstalleerd zonder het vinkje **Add python.exe to PATH**. | Ga naar <https://www.python.org/downloads/>, download **Python 3.12** en zet tijdens het installeren een vinkje bij **Add python.exe to PATH** vóórdat je op *Install* klikt. Start daarna je pc opnieuw op en dubbelklik weer op `install.bat`. |
| **`Python is gevonden, maar is te oud.`** of **`... is te nieuw.`** | JARVIS werkt met Python 3.11 tot en met 3.14. Een oudere of nieuwere versie kent bepaalde onderdelen niet en loopt later vast op een foutmelding die dit niet uitlegt. | Installeer **Python 3.12** ernaast (<https://www.python.org/downloads/>, vinkje **Add python.exe to PATH**). Je hoeft je oude versie niet te verwijderen. Draai daarna `install.bat` opnieuw. |
| **`Node.js is niet gevonden.`** | Node.js ontbreekt. Dat is alleen nodig om het dashboard (de webpagina met grafieken) te bouwen. | Wil je het dashboard: installeer Node.js LTS via <https://nodejs.org/> en draai `install.bat` opnieuw. Wil je het niet: de installatie gaat gewoon verder, de bot zelf werkt zonder Node.js. |
| **`FOUT: installeren van de Python-pakketten is mislukt.`** | Meestal een wegvallende internetverbinding of een firewall/virusscanner die de download tegenhoudt. Soms een halfvolle schijf. | Controleer je internetverbinding en dat er minstens 2 GB vrij is op je schijf. Draai `install.bat` daarna gewoon opnieuw — hij pakt op waar hij was. Blijft het misgaan, kijk dan welke naam er in de foutregel staat; die kun je opzoeken. |
| **`FOUT: kon de Python-omgeving niet aanmaken.`** of **`de Python-omgeving is onvolledig.`** | De map `.venv` is beschadigd geraakt, bijvoorbeeld doordat een eerdere installatie halverwege is afgebroken. | Verwijder de map `.venv` in de projectmap en dubbelklik opnieuw op `install.bat`. In `.venv` staan alleen hulpprogramma's — je gegevens en instellingen staan er niet in. |
| **`FOUT: installeren van de dashboard-onderdelen is mislukt.`** of **`het bouwen van het dashboard is mislukt.`** | Node.js kon de dashboard-onderdelen niet downloaden of bouwen. | De bot werkt hier zonder. Wil je het dashboard toch: controleer je internetverbinding en draai `install.bat` opnieuw. |
| **De installatie is halverwege gestopt** (venster gesloten, pc uitgevallen, stroom weg). | Er staat nu een halve installatie op je schijf. | Dubbelklik gewoon opnieuw op `install.bat`. De installatie is *herhaalbaar*: hij controleert elke stap opnieuw en slaat over wat al klaar is. Je hoeft niets weg te gooien en je verliest niets. |
| **Het zwarte venster verdwijnt meteen.** | Je hebt het bestand geopend vanuit het ZIP-bestand zelf in plaats van uit een uitgepakte map. | Klik met de rechtermuisknop op het ZIP-bestand → **Alles uitpakken**. Open de map die daaruit komt en dubbelklik daar op `install.bat`. |
| **Windows waarschuwt: "Windows heeft uw pc beveiligd".** | SmartScreen kent dit bestand nog niet. Dat gebeurt bij elk programma dat niet door een grote uitgever is ondertekend. | Klik op **Meer informatie** en daarna op **Toch uitvoeren**. Doe dit alleen als je het bestand zelf hebt gedownload en weet waar het vandaan komt. |

---

## Starten en stoppen

| Probleem | Mogelijke oorzaak | Oplossing |
|---|---|---|
| **`Het dashboard kan poort 8000 niet gebruiken.`** | Er luistert al iets op poort 8000. Meestal draait JARVIS al; soms gebruikt een ander programma die poort. | Kijk of er nog een zwart venster van JARVIS openstaat. Zo ja, gebruik `stop.bat` en start daarna opnieuw. Heb je een ander programma dat poort 8000 gebruikt, zet dan `DASHBOARD_PORT=8010` in het bestand `.env` en start opnieuw. |
| **`De control-service kan poort 8770 niet gebruiken.`** | Dezelfde situatie voor de bedieningsdienst — de dienst waarmee de Chrome-extensie praat. | Zelfde aanpak: eerst `stop.bat`, dan opnieuw starten. Moet die poort echt vrij blijven, zet dan `JARVIS_CONTROL_PORT=8771` in `.env`. **Let op:** verander je deze poort, pas hem dan ook aan in de instellingen van de Chrome-extensie, anders vindt die JARVIS niet meer. |
| **`.env` ontbreekt / `Er is nog geen .env`** | De installatie is niet afgerond, of het bestand is per ongeluk verwijderd. Daar staan je API-sleutels en instellingen in. | Dubbelklik op `install.bat`. Bij stap 6 wordt `.env` opnieuw aangemaakt en vraagt hij je sleutels opnieuw. Bestond `.env` al, dan blijft alles wat erin staat gewoon staan — alleen wat je nu invult wordt bijgewerkt. |
| **`Er draait al een JARVIS-bot (procesvergrendeling).`** | Een eerdere bot is niet netjes afgesloten en heeft zijn slot laten staan. | Gebruik `stop.bat`. Helpt dat niet, start je pc opnieuw op en gebruik daarna `start.bat`. |
| **Ik weet niet of JARVIS draait.** | — | Dubbelklik op `diagnose.bat`. Bovenaan staat of de bot, de bewaker en de bedieningsdienst draaien. Je kunt ook de Chrome-extensie openen: die toont dezelfde status. |
| **`stop.bat` zegt: "JARVIS reageert niet".** | Het proces hangt of is al weg zonder dat op te ruimen. | Wacht een halve minuut en probeer `stop.bat` nog eens. Blijft het hangen, start je pc opnieuw op. Er gaan geen gegevens verloren: alles wat de bot bijhoudt wordt direct naar schijf geschreven. |
| **Het venster sluit meteen na het starten.** | Er is een fout die het venster niet kon tonen — zeldzaam, want elk venster hoort open te blijven bij een fout. | Kijk in `logs\loop.log` en `logs\supervisor.log`; onderaan staat wat er is misgegaan. Dubbelklik daarna op `diagnose.bat`. |

---

## API-sleutels

| Probleem | Mogelijke oorzaak | Oplossing |
|---|---|---|
| **De controle zegt: `afgewezen` / `CONFIGURATION_ERROR`.** | De sleutel klopt niet: verkeerd gekopieerd, verlopen, ingetrokken, of hij mist de juiste rechten. | Maak bij de provider een **nieuwe** sleutel aan en plak die opnieuw via `install.bat` (stap 6). Kopieer de hele sleutel, zonder spaties ervoor of erachter. Bij Coinbase moet de sleutel minstens **leesrechten** hebben; om écht te handelen ook handelsrechten — maar zet dat pas aan als je bewust live wilt gaan. |
| **De controle zegt: `niet bereikbaar` / `VERIFICATION_UNAVAILABLE`.** | JARVIS kon de provider niet bereiken: geen internet, een storing bij OpenAI of Coinbase, of een firewall die de verbinding blokkeert. **Dit is géén sleutelprobleem** — er is niets mis met je sleutel. | Controleer je internetverbinding en probeer het over een paar minuten opnieuw. Blijft het: kijk op de statuspagina van OpenAI of Coinbase of er een storing is. Verander je sleutel **niet** — die is waarschijnlijk prima. |
| **De controle zegt: `SETUP_REQUIRED`.** | Er is nog geen sleutel ingevuld. | Dubbelklik op `install.bat` en doorloop stap 6. |
| **De bot stopt met: `De API-sleutels ontbreken of werden afgewezen.`** | De bot is gestart met een sleutel die de provider afwijst. De bewaker herstart hem bewust niet — opnieuw proberen zou hetzelfde resultaat geven. | Vul een geldige sleutel in via `install.bat` (stap 6) en start opnieuw met `start.bat`. |
| **Ik krijg soms wel en soms niet verbinding met de provider.** | Een wisselvallige verbinding. JARVIS probeert het bij een leescontrole automatisch een paar keer opnieuw voordat hij "niet bereikbaar" meldt. | Als het regelmatig gebeurt, ligt het meestal aan je netwerk (wifi, vpn, firewall). De bot zelf gaat hier niet van stuk: hij wacht en probeert het later opnieuw. |
| **Ik wil weten waar mijn sleutels staan.** | — | In het bestand `.env` in de projectmap, op je eigen pc. Ze worden nergens anders heen gestuurd en verschijnen niet in de logboeken. **Deel dat bestand met niemand** en plak je sleutels nergens in een chat. |

---

## De bot draait niet stabiel

| Probleem | Mogelijke oorzaak | Oplossing |
|---|---|---|
| **De bot crasht steeds opnieuw.** | Een fout die zichzelf herhaalt. De bewaker herstart de bot automatisch, met steeds langere pauzes ertussen. | Kijk onderaan in `logs\supervisor.log`: daar staat waarom de bot stopte. Staat er `restart_limit_reached`, dan is de bewaker gestopt met herstarten omdat het duidelijk niet vanzelf goed komt. Los eerst de reden op en gebruik dan `start.bat`. |
| **De bot lijkt gestart, maar stopt direct weer.** | Een fout die pas na het opstarten optreedt — bijvoorbeeld een instelling in `.env` die niet klopt. | JARVIS wacht na het starten drie seconden en meldt de bot pas als "gestart" als hij dan nog draait. Zie je toch dat hij wegvalt: kijk in `logs\loop.log`. Staat daar `code 2`, dan blokkeerde de opstartcontrole de start vanwege een instelling in `.env`; zet die terug op de waarde uit [`.env.example`](.env.example). |
| **Er gebeurt niets herstartbaars: de bot blijft uit.** | De bot is gestopt met een fout waarbij herstarten geen zin heeft (verkeerde instelling, dubbele bot, afgewezen sleutels), óf iemand heeft bewust gestopt. | In `logs\supervisor.log` staat `permanent_error` met de reden erbij. Los die op en start met `start.bat`. Staat er `clean_exit`, dan is de bot netjes gestopt en is er niets aan de hand. |
| **De bot draait, maar plaatst geen orders.** | Dat hoort zo. JARVIS wordt geleverd in **papieren modus**: hij denkt na en houdt bij wat hij zou doen, maar stuurt niets naar Coinbase. | Dit is geen storing. Laat hem eerst een tijd meelopen en kijk in de logboeken wat hij zou hebben gedaan. Live handelen zet je alleen zelf en bewust aan; doe dat niet zolang je twijfelt. |
| **Het internet viel weg terwijl de bot draaide.** | — | Er hoeft niets te gebeuren. JARVIS behandelt een netwerkstoring niet als een fout in je sleutels: hij wacht, probeert het opnieuw met steeds langere pauzes, en gaat verder zodra de verbinding terug is. |
| **De logboeken groeien heel snel.** | `LOG_LEVEL` staat op `DEBUG`. | Zet `LOG_LEVEL=INFO` in `.env` en herstart met `restart.bat`. |

---

## Chrome-extensie

| Probleem | Mogelijke oorzaak | Oplossing |
|---|---|---|
| **`JARVIS draait nu niet op deze pc.`** | De bedieningsdienst draait niet — meestal omdat JARVIS niet gestart is. | Dubbelklik op `start.bat` en wacht tot het venster meldt dat alles draait. Klik daarna in de extensie op **Vernieuwen**. |
| **De extensie kan niet verbinden terwijl JARVIS wél draait.** | De extensie kijkt naar de verkeerde poort, of het toegangswoord in de extensie klopt niet meer. | Open de instellingen van de extensie. Controleer dat de poort hetzelfde is als `JARVIS_CONTROL_PORT` in `.env` (standaard `8770`). Plak daarna het toegangswoord opnieuw: dat staat in `state\control_token.txt`. |
| **`De toegangssleutel werd niet geaccepteerd.`** | Het toegangswoord in de extensie hoort niet meer bij dat van de dienst. Dat gebeurt bijvoorbeeld na een herinstallatie. | Open `state\control_token.txt`, kopieer de hele regel en plak die in de instellingen van de extensie. |
| **De extensie staat er niet in Chrome.** | Hij is nog niet geladen, of Chrome heeft hem uitgezet. | Ga naar `chrome://extensions`, zet **Ontwikkelaarsmodus** rechtsboven aan, klik op **Uitgepakte extensie laden** en kies de map `extension` in de projectmap. |
| **De browser opent niet vanzelf na de installatie.** | Chrome is niet je standaardbrowser, of Windows kon hem niet starten. | Dat is niet erg — er wordt niets overgeslagen. Open Chrome zelf en ga naar `chrome://extensions`. De extensie laad je met de stap hierboven. |
| **De knop "Starten" in de extensie doet niets.** | De dienst draait wel, maar de bot kon niet starten. | Kies onder **Laatste logregels** de optie **Bot** en klik op **Ophalen**. Daar staat de reden. Werkt dat niet, gebruik dan `start.bat` en `diagnose.bat` op de pc zelf. |

---

## Als niets helpt

1. **Dubbelklik op `diagnose.bat`.** Dit controleert alles en verandert niets.
2. **Kijk onderaan in de logboeken** in de map `logs`:
   - `loop.log` — de bot zelf
   - `supervisor.log` — de bewaker die de bot herstart
   - `control_service.log` — de dienst waar de Chrome-extensie mee praat
3. **Draai `install.bat` opnieuw.** Dat is veilig: bestaande instellingen en
   handelsgegevens blijven staan, alleen ontbrekende of kapotte onderdelen
   worden hersteld.

Kom je er niet uit en wil je hulp vragen, deel dan de laatste regels van het
logboek. **Deel nooit je `.env`-bestand en nooit een API-sleutel** — ook niet
als iemand daarom vraagt.

---

## Verder lezen

- [`README.md`](README.md) — de gewone handleiding
- [`HANDLEIDING-WINDOWS.md`](HANDLEIDING-WINDOWS.md) — stap voor stap, met
  uitleg bij elk scherm
- [`INSTALLATIE-WINDOWS.md`](INSTALLATIE-WINDOWS.md) — extra detail over de
  installatie
- [`docs/TECHNISCHE-README.md`](docs/TECHNISCHE-README.md) — voor programmeurs
