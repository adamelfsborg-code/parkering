# Datumparkering Gävle

Karta som visar var du får parkera i Gävle, med hänsyn till datumparkering (1 nov–15 maj, kl 00–06), avgiftszoner och 24-timmarsregeln.

**Sida:** https://adamelfsborg-code.github.io/datumparkering-gavle/

- Grönt/gult/rött per gatusida. Tryck på en sida för att se vilka regler som gäller och om de stoppar dig just nu.
- *Planera parkering*: välj en period (t.ex. en helg) och en plats, så får du förslag sorterade på lämpligast, närmast eller billigast.

## Så funkar det

- **Lokala trafikföreskrifter** (förbud att stanna/parkera, huvudleder, reserverade platser, tillåtna sträckor med tidsgräns) hämtas från Transportstyrelsens RDT med `data/rdt_fetch.py`, tolkas i `data/ltf.py` och kopplas till gatusidor i `data/match.py`. Föreskrifter utan kartdata placeras utifrån texten ("mellan A och B") när det går.
- Zoner med parkeringsförbud och området för datumparkering: Gävle Parkeringsservices kartor (`data/forbudszoner.kml`) och föreskrift 2180 2025:233.
- Gator, husnummer och parkeringsplatser kommer från OpenStreetMap. Vilken sida av gatan som har udda nummer räknas ut från var adresserna ligger (`data/process.py`).
- Avgiftszoner från Gävle Parkeringsservices zonkarta (`data/zones.kml`), priser för parkeringshus i `data/facilities.json`.
- Regellogiken finns i `src/rules.js` och testas med `node --test test/`.

## Bygga om

```sh
# hämta färsk OSM-data (se data/q_*.txt) och föreskrifter:
python3 data/rdt_fetch.py   # kräver pdftotext (poppler)
python3 data/process.py
python3 build.py      # skriver docs/index.html (GitHub Pages) och build/index.html (Claude-artifact)
```

Hjälpmedel, ingen myndighetstjänst. Skyltar på plats gäller alltid. Kartdata © OpenStreetMap-bidragsgivare (ODbL).
