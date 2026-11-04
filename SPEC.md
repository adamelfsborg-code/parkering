# Parkering – specifikation och plan

Status: utkast 2026-11-04. Varje avsnitt under "Arbetspaket" är tänkt att bli en eller flera GitHub-issues.

## Mål

En karta som tydligt visar var, när och hur länge man får parkera på gatan, för hela Sverige, en kommun i taget.
Användare ska kunna rapportera fel och tipsa om platser, och rapporterna ska synas för alla tills någon har granskat dem.

## Nuläge

- **Frontend:** en statisk sida (Leaflet), byggd av `build.py`, på GitHub Pages: https://adamelfsborg-code.github.io/parkering/
- **Data:** byggs lokalt med Python-skript i `data/`:
  - `osm_fetch.py`: gator, adresser och p-platser från OpenStreetMap
  - `rdt_fetch.py`: lokala trafikföreskrifter från Transportstyrelsen (kommuner och länsstyrelser)
  - `ltf.py` och `match.py`: tolkar föreskrifterna och kopplar dem till gatusidor
  - `process.py`: en JSON-fil per kommun
  - `audit.py`: granskar kopplingen
- **Kommuner:** Gävle och Sandviken är publicerade. Data för ytterligare åtta kommuner är hämtad men inte granskad.
- **Inget delat tillstånd:** allt är statiskt, och ingen server finns ännu.

## Beslut

| Fråga | Beslut |
|---|---|
| Repo och hosting | **Privat repo** på GitHub. Appen hostas på **Cloudflare Pages** med förhandsversion per pull request. Repot görs privat först när Cloudflare är uppsatt, så att sidan inte går ned. |
| Server | **Rust**: Axum + SQLx mot **Postgres med PostGIS**. |
| App | **TypeScript** + Vite. Kartan ligger kvar på Leaflet (MapLibre kan prövas senare). |
| Claude-versionen (artifact) | **Avvecklas**. Uppdateras inte längre. |

Öppna frågor:
1. **Adminkonton.** Förslag: inloggning med GitHub (OAuth) och en lista med tillåtna konton. Inga lösenord att hantera.
2. **Positioner (GDPR).** "Var användarna befinner sig" är personuppgifter. Förslaget är att bara spara **grova rutor** (ungefär 5×5 km eller kommunnivå), per dag och utan användar-ID, och bara efter samtycke.
3. **Var servern och databasen körs.** Förslag: servern på **Fly.io** (container i Stockholm, `arn`) och databasen hos **Neon** (hanterad Postgres med PostGIS och gratisnivå). Alternativ: Railway, eller Postgres på Fly.

## Arkitektur

```
Användare ── app (TypeScript, Cloudflare Pages)
               │  läser: kommundata (JSON via CDN)
               │  anropar: /api (rapporter, tips, överstyrningar, besök, admin)
               ▼
            server (Rust: Axum + SQLx, Fly.io)
              ├─ Postgres + PostGIS (Neon)   rapporter, överstyrningar, regioner, besök
              ├─ GitHub OAuth                 inloggning för adminer
              ├─ Cloudflare Turnstile         spamskydd (verifieras i servern)
              ├─ Discord/Slack-webhook        notis vid ny rapport
              └─ R2/S3 (senare)               foton av skyltar

GitHub Actions
   CI: app (typkontroll, vitest), server (cargo fmt/clippy/test), pipeline (audit)
   Natt: osm_fetch → rdt_fetch → process (+ godkända överstyrningar från servern) → audit → publicera kommundata
```

Repostruktur:

```
app/        TypeScript-appen (nuvarande src/ + build.py flyttas hit och görs om till Vite)
server/     Rust-servern (Axum, SQLx, migreringar i server/migrations)
pipeline/   databygget (nuvarande data/*.py; kan portas till Rust senare)
SPEC.md
```

API (första version):

| Metod | Väg | Vem | Vad |
|---|---|---|---|
| GET | `/api/health` | alla | hälsokontroll |
| GET | `/api/regions` | alla | stödda kommuner och status |
| GET | `/api/reports?bbox=` | alla | öppna rapporter i kartvyn (för flaggning) |
| POST | `/api/reports` | alla (Turnstile) | ny rapport eller nytt tips |
| GET | `/api/overrides?region=` | alla | godkända rättelser |
| POST | `/api/visits` | alla (samtycke) | grov ruta och kommun |
| GET/PATCH | `/api/admin/reports…` | admin | kö, granska, rätta |
| GET | `/api/admin/coverage` | admin | Sverigekarta: kommuner och efterfrågan |

### Datamodell (första version)

| Tabell | Innehåll |
|---|---|
| `regions` | kommun-id, namn, kommunkod, status (`live`, `beta`, `planerad`), gränspolygon |
| `reports` | id, tid, kommun, gatubit (OSM-väg + bit + sida), typ (`cannot_park`, `wrong_info`, `can_park`), kommentar, position, ev. foto, status (`open`, `confirmed`, `rejected`, `fixed`), granskare, beslutstext |
| `overrides` | godkänd rättelse som läggs ovanpå genererad data: gatubit/sida eller ny geometri, effekt (`hide`, `allow`, `ban`, regler/tider), källa (rapport-id, skylt, föreskrift), giltig från/till |
| `visits` | dag, grov ruta (eller kommun), antal. Ingen användaridentitet |

Gatubitarnas id måste vara stabila mellan databyggen (t.ex. OSM-väg-id + start/slut i meter), annars tappar rapporter sin plats när data byggs om. Det ingår i E1.

## Arbetspaket

### E1 – Infrastruktur (först)

- [ ] Repostruktur `app/`, `server/` och `pipeline/`.
- [ ] Appen till TypeScript + Vite, med samma funktion och tester.
- [ ] Cloudflare Pages från repot, förhandsversion per pull request, repot privat.
- [ ] Rust-server: skelett, konfiguration, loggning, Dockerfile och deploy till Fly.io.
- [ ] Databas: Postgres + PostGIS (Neon) och SQLx-migreringar för `regions`, `reports`, `overrides` och `visits`.
- [ ] CI i GitHub Actions för app, server och pipeline.
- [ ] Nattligt databygge i Actions med cachad rådata. Overpass är långsamt och överbelastat.
- [ ] Stabila id för gatubitar.
- [ ] Hemligheter och miljöer (dev/prod). Inga nycklar i klientkoden.

**Klart när:** en push till `main` bygger, testar och publicerar app och server automatiskt, kommundata uppdateras varje natt, och appen kan läsa och skriva en testrad via servern.

### E2 – Rapportera fel

- [ ] Längst ned i gaturutan: **"Rapportera problem"** med valen *"Här får man inte parkera"*, *"Detta stämmer nog inte"* och fritext. Valfritt foto av skylten.
- [ ] Rapporten kopplas till gatubit och sida, plus användarens position om den finns.
- [ ] Flaggade bitar syns för **alla** tills de granskats, t.ex. med streckad linje och texten "Under granskning: N rapporter".
- [ ] Spamskydd: Cloudflare Turnstile eller hCaptcha, och en gräns för antal rapporter per enhet och dag.
- [ ] En kanal för all feedback: kön på adminsidan plus en notis (Slack, Discord eller e-post) för varje ny rapport.

**Klart när:** en rapport från mobilen syns flaggad för andra användare inom en minut och dyker upp i adminkön och i notiskanalen.

### E3 – "Här går det visst att parkera"

- [ ] Användaren markerar en plats eller sträcka på kartan, väljer sida och anger valfritt tider, maxtid, avgift och foto.
- [ ] Servern hämtar automatiskt det som går att få fram: föreskrifter i RDT nära punkten, p-platser i OSM, avgiftszon och datumparkering. Det visas som underlag för granskaren.
- [ ] Godkänd plats blir en **överstyrning** som syns för alla och följer med i varje databygge.

**Klart när:** ett godkänt tips syns som en grön sträcka för alla, med källa ("tips från användare, granskat <datum>").

### E4 – Adminsida

- [ ] Inloggning med GitHub, bara för konton på listan över adminer.
- [ ] **Kö** med rapporter och tips. Per post: karta, gatubitens regler, underlag från E3 och knapparna *Bekräfta*, *Avvisa* och *Rätta*.
- [ ] *Rätta* skapar en överstyrning, eller ett issue när felet ligger i tolkningskoden.
- [ ] **Sverigekarta** med kommunerna färgade efter status (`live`, `beta`, `planerad`) och en värmekarta över var användarna finns (grova rutor, bara samtyckta).
- [ ] Lista över kommuner sorterade på "efterfrågan utan stöd" (besök i kommuner som inte stöds), som underlag för vilka som läggs till härnäst.

**Klart när:** en admin kan granska en rapport från början till slut, och Sverigekartan visar stödda kommuner och efterfrågan.

### E5 – Kortare gaturuta

- [ ] Överst bara nyckeltalen: **status nu**, **när du får stå här** (se E6), **maxtid**, **avgift** och **nästa förbud**.
- [ ] Varje regel på en rad med ikon och kort text, t.ex. "Datumparkering: jämna sidan i natt" eller "Max 2 h vardagar 9–19".
- [ ] **"Visa detaljer"** fäller ut fullständiga regler, föreskriftstexter och länkar.

**Klart när:** rutan får plats ovanför vecket på en mobil, utan att man behöver scrolla, för en vanlig gata med 2–3 regler.

### E6 – När och hur länge kan jag stå här?

- [ ] Räkna ut tillgängliga tidsblock per gatusida för de närmaste 7 dagarna utifrån alla regler (förbud med tider, datumparkering, maxtid, avgiftstider, 24-timmarsregeln).
- [ ] Visa en tidslinje, t.ex. "Förbjudet nu (17:00). Tillåtet 20:00–08:00. Därefter max 2 h, avgift 15 kr/h 9–19."
- [ ] Logiken ligger i `rules.js` och testas med enhetstester (finns delvis redan: `schedActive`, `datumNext`, `counted24`).

**Klart när:** rutan visar korrekta block för minst tio testfall med kända svar, som datumparkering, städnatt och maxtid i avgiftszon.

### E7 – Välj period (från–till)

- [ ] Ersätt "Välj tid" med ett periodläge där man väljer från och till.
- [ ] Färger för perioden: **grön** = tillåtet hela perioden, **gul** = delvis, **röd** = inte alls.
- [ ] Gaturutan visar vilka block i perioden som är tillåtna.
- [ ] Planeraren (dold just nu) byggs om ovanpå detta.

**Klart när:** en helg (fre 16 – sön 20) ger rätt färger och block i Gävle, där datumparkeringen byter sida varje natt.

### E8 – Fler kommuner

- [ ] Process per kommun: hämta, bygga, kör `audit.py`, stickprov mot skyltar och sätt status `beta`, sedan `live`.
- [ ] Nästa i tur: Uppsala, Hofors, Ockelbo, Älvkarleby, Tierp, Söderhamn, Östhammar och Heby (data hämtad).
- [ ] Kommunspecifika källor (zonkartor, priser) samlas i `regions.json`, så att allt annat är generellt.

### E9 – Kvalitet och drift

- [ ] `audit.py` i CI med tröskelvärden som stoppar publicering vid kraftig försämring.
- [ ] Visa ålder på data per kommun.
- [ ] Respektera källornas villkor: Overpass och OSM-kartbilder har användningsregler. Vid fler användare behövs egna kartbilder eller en betald tjänst (t.ex. MapTiler). Kontakta Transportstyrelsen om bättre åtkomst till RDT.
- [ ] Ansvarsfriskrivning: appen tolkar föreskrifter, och skyltar gäller alltid.

## Ordning

1. **E1 Infrastruktur**: repostruktur, TypeScript-app, Cloudflare Pages, Rust-server, databas, CI.
2. **E5 + E6**: kortare ruta och "när och hur länge". Kräver ingen backend och ger mest för användaren direkt.
3. **E2 Rapportera fel** och **E4 Adminsida** (kö först, Sverigekartan sedan).
4. **E7 Periodläge** och planeraren tillbaka.
5. **E3 Tips om platser**.
6. **E8 Fler kommuner** löpande, efter att E2 finns, så att användarna kan hjälpa till att hitta fel.
