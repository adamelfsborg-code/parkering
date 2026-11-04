"""Tolkar Gävles lokala trafikföreskrifter (hämtade med rdt_fetch.py) till regler med geometri.

Varje regel får:
  kind   – nostop | nopark | mainroad | pedestrian | reserved | allow | area_nopark
  side   – väderstreck från texten (t.ex. "S" för "södra sidan") eller None = båda sidor
  sched  – tidsfönster när regeln gäller, eller None = alltid
  unparsed – texten nämner tider som inte gick att tolka (behandlas som "alltid")
  maxH   – maxtid i timmar för tillåten parkering
  geom   – lista av linjer/ytor i WGS84
"""
import csv
import json
import os
import re
import sys

from sweref import to_wgs84

HERE = os.path.dirname(os.path.abspath(__file__))
RDT_ROOT = os.path.join(HERE, "rdt")

DIRS = {"norra": "N", "södra": "S", "östra": "E", "västra": "W", "nordöstra": "NE", "nordvästra": "NW",
        "sydöstra": "SE", "sydvästra": "SW"}
WEEKDAYS = {"måndag": 1, "tisdag": 2, "onsdag": 3, "torsdag": 4, "fredag": 5, "lördag": 6, "söndag": 0,
            "mån": 1, "tis": 2, "ons": 3, "tor": 4, "fre": 5, "lör": 6, "sön": 0}
MONTHS = {m: i + 1 for i, m in enumerate(["januari", "februari", "mars", "april", "maj", "juni", "juli",
                                          "augusti", "september", "oktober", "november", "december"])}


def operative_text(txt):
    """Själva föreskriften: texten efter 'följande.' fram till ikraftträdandet."""
    t = re.sub(r"[ \t]+", " ", txt)
    m = (re.search(r"föreskriver\b.*?följande\s*[.:]", t, re.S)
         or re.search(r"föreskriver\b.{0,300}?\(1998:1276\)\s*\.?", t, re.S))
    if m:
        i = m.end()
    else:
        m = re.search(r"Beslutade den [^\n]*\n", t)
        i = m.end() if m else 0
    j = len(t)
    for stop in ("Dessa föreskrifter träder", "Denna föreskrift träder", "Denna författning träder", "Dessa föreskrifter trä"):
        k = t.find(stop, i)
        if k >= 0:
            j = min(j, k)
    return re.sub(r"\s+", " ", t[i:j]).strip()


FEE = re.compile(r"avgift", re.I)


def split_fee(text):
    """Delar upp i (övrigt, avgiftstext). Avgiftstider är när man betalar, inte när regeln gäller."""
    parts = [p for p in re.split(r"(?<=\.)\s+(?=\d+\s?§|[A-ZÅÄÖ])", text) if p.strip()]
    fee = [p for p in parts if FEE.search(p)]
    return " ".join(p for p in parts if not FEE.search(p)).strip(), " ".join(fee).strip()


def split_datum(text):
    """Delar upp texten i (övrigt, egen datumparkering).

    Många tillåtelser har egna paragrafer om datumparkering, t.ex.
    "7 § ... udda datum ... 8 § Förbudet i 7 § gäller mellan klockan 00 – 08 från 1 oktober till 15 maj".
    De plockas ut så att de inte tolkas som tider för själva tillåtelsen.
    """
    parts = [p for p in re.split(r"(?<=\.)\s+(?=\d+\s?§|[A-ZÅÄÖ])", text) if p.strip()]
    datum_par = set()
    for p in parts:
        if re.search(r"udda datum|jämnt datum|jämna datum", p, re.I):
            m = re.match(r"\s*(\d+)\s?§", p)
            if m:
                datum_par.add(m.group(1))
    keep, datum = [], []
    for p in parts:
        ref = re.search(r"Förbudet i (\d+)\s?§", p)
        if re.search(r"udda datum|jämnt datum|jämna datum|datumparkering", p, re.I) or (ref and ref.group(1) in datum_par):
            datum.append(p)
        else:
            keep.append(p)
    override = None
    if datum:
        dt = " ".join(datum)
        m = RANGE.search(dt)
        months = parse_months(dt)
        if m:
            h1, m1, h2, m2 = m.groups()
            override = {"f": int(h1) * 60 + int(m1 or 0), "t": int(h2) * 60 + int(m2 or 0), "m": months}
    return " ".join(keep).strip(), override


def classify(rubrik, text):
    r = rubrik.lower()
    t = text.lower()
    if "datumparkering" in r:
        return "datum"
    if re.search(r"(område|zon) med förbud att parkera", r):
        return "area_nopark"
    if "stanna" in r and ("förbud" in r or "får inte" in t):
        return "nostop"
    if "förbud" in r and "parkera" in r:
        return "nopark"
    if "huvudled" in r:
        return "mainroad"
    if "gågata" in r or "gångfart" in r:
        return "pedestrian"
    if ("ändamålsplats" in r or "rörelsehindrade" in r or "laddplats" in r or "lastplats" in r
            or re.search(r"endast (motorcyklar|bussar|buss|lastbil|fordon som|elfordon|taxi|mopeder)", t)
            or "på- och avstigning" in r):
        return "reserved"
    if "parkering" in r:
        if re.search(r"får (fordon )?parkeras|fordon får parkeras", t):
            return "allow"
        if re.search(r"får (inte|ej) (fordon )?parkeras|fordon får (inte|ej) parkeras", t):
            return "nopark"
        return "allow"
    return None


def reserved_for(text):
    t = text.lower()
    for pat, label in ((r"taxi", "taxi"), (r"lastning och lossning", "lastning och lossning"),
                       (r"rörelsehindrade", "rörelsehindrade med tillstånd"), (r"på- (eller|och) avstigning", "på- och avstigning"),
                       (r"laddning|laddplats|elfordon", "laddning av elfordon"), (r"motorcykl", "motorcyklar"),
                       (r"buss", "bussar"), (r"moped", "mopeder"), (r"polis", "polisfordon"), (r"lastbil", "lastbilar")):
        if re.search(pat, t):
            return label
    return "särskilt ändamål"


def parse_side(text):
    """Väderstreck för sidan, eller None om inget anges eller om flera olika sidor nämns (= båda)."""
    found = {DIRS[m.lower()] for m in re.findall(r"\b(nordöstra|nordvästra|sydöstra|sydvästra|norra|södra|östra|västra)\s+(?:och \w+ )?sid", text, re.I)}
    found |= {DIRS[m.lower()] for m in re.findall(r"\b\w+s (nordöstra|nordvästra|sydöstra|sydvästra|norra|södra|östra|västra) sida", text, re.I)}
    found |= {DIRS[m.lower()] for m in re.findall(r"\b(nordöstra|nordvästra|sydöstra|sydvästra|norra|södra|östra|västra) och (?:nordöstra|nordvästra|sydöstra|sydvästra|norra|södra|östra|västra)\s+sid", text, re.I)}
    found |= {DIRS[m.lower()] for m in re.findall(r"\b(?:nordöstra|nordvästra|sydöstra|sydvästra|norra|södra|östra|västra) och (nordöstra|nordvästra|sydöstra|sydvästra|norra|södra|östra|västra)\s+sid", text, re.I)}
    return found.pop() if len(found) == 1 else None


TIME = r"(\d{1,2})(?:[.:](\d{2}))?"
RANGE = re.compile(r"(?:kl(?:ockan)?\.?\s*|mellan\s+klockan\s+|mellan\s+kl\.?\s*)" + TIME + r"\s*(?:-|–|—|och|till)\s*(?:kl\.?\s*)?" + TIME, re.I)


def parse_days(seg):
    """Dagspecifikation i en textbit. Returnerar lista av koder eller None."""
    s = seg.lower()
    if re.search(r"vardag(ar)? utom (vardag|dag) före sön- och helgdag", s):
        return ["wk"]
    if re.search(r"(vardag|dag) före sön- och helgdag", s):
        return ["pre"]
    if re.search(r"sön- och helgdag", s):
        return ["hol"]
    if re.search(r"\bvardagar\b|\bvardag\b", s):
        return ["wk", "pre"]
    m = re.search(r"\b(måndag|tisdag|onsdag|torsdag|fredag|lördag|söndag|mån|tis|ons|tor|fre|lör|sön)(?:ar|en)?\s*(?:-|–|till)\s*(måndag|tisdag|onsdag|torsdag|fredag|lördag|söndag|mån|tis|ons|tor|fre|lör|sön)", s)
    if m:
        a, b = WEEKDAYS[m.group(1)], WEEKDAYS[m.group(2)]
        days, d = [], a
        while True:
            days.append(f"d{d}")
            if d == b:
                break
            d = (d + 1) % 7
        return days
    found = [f"d{WEEKDAYS[w]}" for w in re.findall(r"\b(måndag|tisdag|onsdag|torsdag|fredag|lördag|söndag)(?:ar|en)?\b", s)]
    if found:
        return (["helgfri"] if "helgfri" in s else []) + found
    return None


def parse_months(text):
    m = re.search(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s*(?:-|–|till och med|till|t\.o\.m\.?)\s*(?:den\s+)?(\d{1,2})\s+(" + "|".join(MONTHS) + ")", text, re.I)
    if not m:
        return None
    return [MONTHS[m.group(2).lower()], int(m.group(1)), MONTHS[m.group(4).lower()], int(m.group(3))]


def parse_schedule(text):
    """Tidsfönster [{d: [dagkoder] | None, f: minut, t: minut}], plus om något inte gick att tolka."""
    windows = []
    pos = 0
    for m in RANGE.finditer(text):
        h1, m1, h2, m2 = m.groups()
        f = int(h1) * 60 + int(m1 or 0)
        t = int(h2) * 60 + int(m2 or 0)
        if not (0 <= f <= 1440 and 0 <= t <= 1440):
            continue
        # dagar: närmast före tiden, annars direkt efter
        sent = max(text.rfind(". ", 0, m.start()), text.rfind("§", 0, m.start()))
        before = text[max(pos, sent + 1):m.start()]
        after = re.split(r"[,.]|\soch\s", text[m.end():m.end() + 80])[0]
        days = parse_days(before) or parse_days(after)
        windows.append({"d": days, "f": f, "t": t})
        pos = m.end()
    months = parse_months(text)
    mentions_time = bool(re.search(r"\bkl\b|klockan|(?<![\d:])\d{1,2}[.:]\d{2}(?!\d)", text, re.I))
    weird = bool(re.search(r"(udda|jämna) veckor|vecka \d|första .{0,20}(månad|vecka)", text, re.I))
    unparsed = (mentions_time and not windows) or weird
    if not windows and not months:
        return None, unparsed
    if not windows:
        windows = [{"d": parse_days(text), "f": 0, "t": 1440}]
    if months:
        for w in windows:
            w["m"] = months
    return windows, unparsed


def parse_maxh(text):
    m = re.search(r"(?:högst|som längst(?: ske)?(?: under)?) (\d+|en|två|tre|fyra) (timm(?:e|ar)|minuter)", text, re.I)
    if not m:
        return None
    n = {"en": 1, "två": 2, "tre": 3, "fyra": 4}.get(m.group(1).lower(), None) or int(m.group(1))
    return n / 60 if m.group(2).startswith("min") else n


def to_lines(geojson):
    """GeoJSON (SWEREF99 TM) -> (linjer, ytor, punkter) i WGS84."""
    lines, polys, points = [], [], []
    conv = lambda cs: [to_wgs84(x, y) for x, y in cs]
    geoms = [f.get("geometry") or {} for f in geojson.get("features", [])]
    while geoms:
        g = geoms.pop()
        t, c = g.get("type"), g.get("coordinates")
        if t == "GeometryCollection":
            geoms += g.get("geometries") or []
            continue
        if t == "LineString":
            lines.append(conv(c))
        elif t == "MultiLineString":
            lines += [conv(x) for x in c]
        elif t == "Polygon":
            polys.append(conv(c[0]))
        elif t == "MultiPolygon":
            polys += [conv(p[0]) for p in c]
        elif t == "Point":
            points.append(to_wgs84(*c[:2]))
        elif t == "MultiPoint":
            points += [to_wgs84(*p[:2]) for p in c]
    return lines, polys, points


def load(kod, forbud_kml=None, lan=None, inside=None):
    """Alla tolkade föreskrifter för en kommun (beteckningskod), plus ev. förbudszoner från KML.

    lan: länsstyrelsens beteckningskod (t.ex. 21FS). Länets föreskrifter gäller statliga vägar
    (huvudleder, förbud m.m.), hänvisar till vägnummer och kopplas bara via geometri. inside(lat, lon)
    avgör vilka av dem som ligger i kommunen.
    """
    rules = _load_code(kod)
    if lan and os.path.exists(os.path.join(RDT_ROOT, lan, "export.csv")):
        for r in _load_code(lan):
            pts = [p for ln in r["lines"] for p in ln] + [p for pg in r["polys"] for p in pg] + r["points"]
            if pts and (inside is None or any(inside(*p) for p in pts[:: max(1, len(pts) // 20)])):
                r["street"] = ""  # vägnummer, inte gatunamn: koppla bara på geometri
                r["county"] = True
                rules.append(r)
    return rules + (forbud_zones(forbud_kml, zone_boundary_streets(kod)) if forbud_kml else [])


def _load_code(kod):
    RDT = os.path.join(RDT_ROOT, kod)
    rows = list(csv.DictReader(open(os.path.join(RDT, "export.csv"), encoding="utf-8"), delimiter=";"))
    rules = []
    for r in rows:
        fid = r["Länk till föreskrift"].split("ForeskriftId=")[1]
        gp, tp = os.path.join(RDT, "geo", fid + ".json"), os.path.join(RDT, "txt", fid + ".txt")
        if not (os.path.exists(gp) and os.path.exists(tp)):
            continue
        text = operative_text(open(tp, encoding="utf-8").read())
        rule_text, datum = split_datum(text)
        kind = classify(r["Rubrik"], rule_text)
        if re.search(r"upphöra att gälla|upphör att gälla|ska upphävas|upphävs", text) and not re.search(r"får (inte )?(fordon )?(parkeras|stannas)", text):
            kind = None  # upphäver en annan föreskrift
        if not kind:
            continue
        raw = open(gp, encoding="utf-8").read() or "{}"
        if '"geometries": EMPTY' in raw:
            raw = raw.replace('"geometries": EMPTY', '"geometries": []')  # RDT:s sätt att säga "ingen geometri"
        try:
            geo = json.loads(raw)
        except json.JSONDecodeError:
            print(f"varning: trasig geometri i {r['Beteckning']}", file=sys.stderr)
            geo = {}
        lines, polys, points = to_lines(geo)
        if kind == "area_nopark" and not polys:
            continue  # saknar geometri (i Gävle ersatt av förbudszonerna från Gävle Parkeringsservice)
        if kind == "datum":
            if not lines:
                continue  # områdesregler hanteras av datum_area()
            datum = parse_datum_spec(text)
            if not datum:
                continue
        rule_text, fee_text = split_fee(rule_text)
        sched, unparsed = parse_schedule(rule_text)
        fee_sched = parse_schedule(fee_text)[0] if fee_text else None
        max_h = parse_maxh(rule_text + " " + fee_text) if kind == "allow" else None
        # "Parkering får som längst ske två timmar i följd under avgiftsbelagd tid" -> maxtiden gäller under avgiftstiden
        max_sched = fee_sched if re.search(r"avgiftsbelagd tid|avgiftspliktig tid", text, re.I) else sched
        street = re.sub(r"^.*?\s(?:på|i|vid|längs)\s*", "", r["Rubrik"]).strip()
        rules.append({
            "id": fid, "bet": r["Beteckning"], "kind": kind, "street": street,
            "text": text[:2000], "side": parse_side(text), "sched": sched, "unparsed": unparsed,
            "maxH": max_h, "maxSched": max_sched if max_h else None, "feeSched": fee_sched,
            "anordnad": bool(re.search(r"särskilt anordnad", text, re.I)),
            "for": reserved_for(text) if kind == "reserved" else None,
            "datum": datum,
            "fee": (lambda m: int(m.group(1)) if m else None)(re.search(r"[Aa]vgiften är (\d+) kr", fee_text)),
            "lines": lines, "polys": polys, "points": points,
        })
    return rules


def tatort_polys(kod):
    """Ytor för tättbebyggt område enligt kommunens föreskrifter (de som har kartdata i RDT).

    Utanför tättbebyggt område ska fordon parkeras utanför körbanan (trafikförordningen 3 kap. 48 §),
    så där ritas inga gatusidor. Returnerar (ytor, föreskrifter utan karta).
    """
    RDT = os.path.join(RDT_ROOT, kod)
    rows = [r for r in csv.DictReader(open(os.path.join(RDT, "export.csv"), encoding="utf-8"), delimiter=";")
            if "tättbebyggt" in r["Rubrik"].lower()]
    polys, missing = [], []
    for r in rows:
        fid = r["Länk till föreskrift"].split("ForeskriftId=")[1]
        gp = os.path.join(RDT, "geo", fid + ".json")
        raw = (open(gp, encoding="utf-8").read() if os.path.exists(gp) else "") or "{}"
        try:
            _, ps, _ = to_lines(json.loads(raw.replace('"geometries": EMPTY', '"geometries": []')))
        except json.JSONDecodeError:
            ps = []
        polys += ps
        if not ps:
            missing.append(r["Beteckning"] + " " + r["Rubrik"][r["Rubrik"].find(" om ") + 4:])
    return polys, missing


def zone_boundary_streets(kod):
    """Gränsgator som ingår i någon zon med parkeringsförbud.

    Zonföreskrifterna beskriver gränsen i text, t.ex. "begränsas av Västra vägen – Valbogatan –
    Norrtullsgatan … (Västra vägen och Valbogatan undantagna)". Gator som står i gränsen men inte
    är undantagna omfattas av förbudet. Returnerar normaliserade gatunamn.
    """
    RDT = os.path.join(RDT_ROOT, kod)
    rows = list(csv.DictReader(open(os.path.join(RDT, "export.csv"), encoding="utf-8"), delimiter=";"))
    norm = lambda n: re.sub(r"[^a-zåäöé]", "", n.lower())
    included = set()
    for r in rows:
        if not re.search(r"(område|zon) med förbud att parkera", r["Rubrik"], re.I):
            continue
        fid = r["Länk till föreskrift"].split("ForeskriftId=")[1]
        tp = os.path.join(RDT, "txt", fid + ".txt")
        if not os.path.exists(tp):
            continue
        text = operative_text(open(tp, encoding="utf-8").read())
        m = re.search(r"begränsas av (.*?)(?:fordon|får)\b", text)
        if not m:
            continue
        desc = m.group(1)
        paren = " ".join(re.findall(r"\(([^)]*)\)", desc))
        if "gränsgatorna undantagna" in paren:
            continue
        excluded = {norm(x) for x in re.split(r",|\soch\s", re.sub(r"\s*undantagna?|\s*ingår.*", "", paren)) if x.strip()}
        for part in re.split(r"\s*[–\-]\s*|,|\soch\s", re.sub(r"\([^)]*\)", "", desc)):
            name = re.sub(r"\b(strax|omedelbart|dess|därifrån|en punkt|en rak linje)\b.*", "", part).strip()
            if re.match(r"[A-ZÅÄÖ]", name) and norm(name) not in excluded and "järnväg" not in name.lower():
                included.add(norm(name))
    return included


def kml_polys(path):
    """Polygoner (lat, lon) från en Google My Maps-export."""
    import xml.etree.ElementTree as ET
    ns = "{http://www.opengis.net/kml/2.2}"
    out = []
    for pm in ET.parse(path).getroot().iter(ns + "Placemark"):
        c = pm.find(f".//{ns}outerBoundaryIs//{ns}coordinates")
        if c is not None:
            out.append([(float(v.split(",")[1]), float(v.split(",")[0])) for v in c.text.split()])
    return out


def forbud_zones(path, boundary=frozenset()):
    """Parkeringsförbudszonerna enligt Gävle Parkeringsservices karta (forbudszoner.kml).

    Motsvarar föreskrifterna om "område med förbud att parkera fordon" (t.ex. 2180 2017:345
    Centrum), som i RDT saknar geometri och bara beskriver gränserna i text.
    """
    return [{
        "id": "forbudszon-%d" % i, "bet": "Förbudszon", "kind": "area_nopark", "street": "",
        "text": ("Område med förbud att parkera fordon. Inom området får du bara parkera där det är "
                 "särskilt tillåtet, oftast på markerade och skyltade platser. Zonen enligt Gävle "
                 "Parkeringsservices karta över parkeringsförbudszoner (bl.a. föreskrift 2180 2017:345 Centrum)."),
        "side": None, "sched": None, "unparsed": False, "boundaryStreets": boundary, "maxH": None, "maxSched": None, "feeSched": None, "anordnad": False, "for": None, "datum": None, "fee": None,
        "lines": [], "polys": [ring], "points": [],
    } for i, ring in enumerate(kml_polys(os.path.join(HERE, path)))]


def parse_datum_spec(text):
    """Tid och period för datumparkering ur föreskriftstext: {f, t, m} eller None."""
    m = RANGE.search(text)
    months = parse_months(text)
    if not m:
        # t.ex. Hofors: "Förbudet gäller alla dagar under tiden 1 oktober till och med 31 maj" = hela dygnet
        return {"f": 0, "t": 1440, "m": months} if months else None
    h1, m1, h2, m2 = m.groups()
    return {"f": int(h1) * 60 + int(m1 or 0), "t": int(h2) * 60 + int(m2 or 0), "m": months}


def datum_area(kod, fallback_kml=None):
    """Kommunens allmänna datumparkering: {bet, spec, polys | None (= hela kommunen), text} eller None.

    Väljer den senaste föreskriften om datumparkering som gäller ett område (inte en enskild gata).
    """
    RDT = os.path.join(RDT_ROOT, kod)
    rows = list(csv.DictReader(open(os.path.join(RDT, "export.csv"), encoding="utf-8"), delimiter=";"))
    rows = [r for r in rows if "datumparkering" in r["Rubrik"].lower()]
    rows.sort(key=lambda r: r["Träder i kraft"])
    for r in reversed(rows):
        fid = r["Länk till föreskrift"].split("ForeskriftId=")[1]
        tp, gp = os.path.join(RDT, "txt", fid + ".txt"), os.path.join(RDT, "geo", fid + ".json")
        if not os.path.exists(tp):
            continue
        text = operative_text(open(tp, encoding="utf-8").read())
        spec = parse_datum_spec(text)
        if not spec:
            continue
        try:
            lines, polys, _ = to_lines(json.loads(open(gp, encoding="utf-8").read() or "{}"))
        except (FileNotFoundError, json.JSONDecodeError):
            lines, polys = [], []
        exempt = bool(re.search(r"gäller inte (inom|på) särskilt anordnade? parkeringsplats", text, re.I))
        if polys:
            return {"bet": r["Beteckning"], "spec": spec, "polys": polys, "text": text[:800], "exemptAnordnad": exempt}
        if not lines and re.search(r"inom (hela )?(\w+ )?(tätort|tättbebyggt område|kommunen|området)", text, re.I):
            # område utan kartdata: räkna konservativt med hela regionen
            polys = kml_polys(os.path.join(HERE, fallback_kml)) if fallback_kml else None
            return {"bet": r["Beteckning"], "spec": spec, "polys": polys, "text": text[:800], "exemptAnordnad": exempt}
    if fallback_kml:
        return {"bet": None, "spec": {"f": 0, "t": 360, "m": [11, 1, 5, 15]}, "polys": kml_polys(os.path.join(HERE, fallback_kml)), "text": "", "exemptAnordnad": True}
    return None


if __name__ == "__main__":
    from collections import Counter
    import sys
    rs = load(sys.argv[1] if len(sys.argv) > 1 else "2180")
    print(datum_area(sys.argv[1] if len(sys.argv) > 1 else "2180"))
    print(len(rs), Counter(r["kind"] for r in rs))
    print("utan geometri:", sum(1 for r in rs if not (r["lines"] or r["polys"] or r["points"])))
    print("med tider:", sum(1 for r in rs if r["sched"]), "otolkade tider:", sum(1 for r in rs if r["unparsed"]))
    print("geometrityper:", Counter(("L" if r["lines"] else "") + ("P" if r["polys"] else "") + ("o" if r["points"] else "") for r in rs))
