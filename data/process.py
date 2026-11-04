"""Bygger kompakt gatu- och regeldata per region (kommun).

    python3 data/process.py            # alla regioner i data/regions.json
    python3 data/process.py sandviken  # en region

Indata:  data/raw/<id>/{streets,addr,parking,base}.json (osm_fetch.py), data/rdt/<kod>/ (rdt_fetch.py)
Utdata:  build/data/<id>.json och build/data/regions.json

För varje gata räknas ut vilken sida (vänster/höger i ritriktningen) som har
udda husnummer, genom att projicera adresspunkter med samma gatunamn på gatan.
Lokala trafikföreskrifter kopplas till gatubitar (ltf.py + match.py).
"""
import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ltf  # noqa: E402
import match  # noqa: E402
OUT_DIR = os.path.join(HERE, "..", "build", "data")

PARKING_HW = {"primary", "secondary", "tertiary", "unclassified", "residential",
              "living_street", "road"}
# Vägtyper som ritas som bakgrund (ej klickbara)
BASE_HW = {"service", "motorway", "motorway_link", "trunk", "trunk_link",
           "primary_link", "secondary_link", "tertiary_link", "pedestrian"}
HW_CODE = {h: i for i, h in enumerate(sorted(PARKING_HW | BASE_HW))}

KY = 110540
KX = 111320 * math.cos(math.radians(60.67))  # sätts om per region i process_region()
MAX_DIST = 70  # m, adress -> gata


def xy(lat, lon):
    return (lon * KX, lat * KY)


def inv(x, y):
    return (y / KY, x / KX)


def norm(name):
    return re.sub(r"\s+", " ", name.strip().lower())


def side_info(p, pts):
    """Minsta avstånd från p till polylinjen pts + tecken (1 = vänster)."""
    best = (1e18, 0)
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        l2 = dx * dx + dy * dy
        t = 0 if l2 == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
        cx, cy = a[0] + t * dx, a[1] + t * dy
        d = math.hypot(p[0] - cx, p[1] - cy)
        if d < best[0]:
            cross = dx * (p[1] - a[1]) - dy * (p[0] - a[0])
            best = (d, 1 if cross > 0 else -1)
    return best


def osm_parking_flags(tags):
    """Returnerar (vänster_förbjuden, höger_förbjuden) från OSM-taggar."""
    def forbidden(side):
        for key in (f"parking:{side}", "parking:both"):
            v = tags.get(key)
            if v in ("no", "separate"):
                return True
            r = tags.get(key + ":restriction")
            if r in ("no_parking", "no_stopping", "no_standing"):
                return True
        for key in (f"parking:lane:{side}", "parking:lane:both"):
            if tags.get(key) in ("no", "no_parking", "no_stopping", "fire_lane"):
                return True
        return False
    return forbidden("left"), forbidden("right")


def parse_zones(path):
    """Avgiftszoner från Gävle Parkeringsservices Google My Maps-export (KML)."""
    import xml.etree.ElementTree as ET
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    zones = []
    for pm in ET.parse(path).getroot().iter("{http://www.opengis.net/kml/2.2}Placemark"):
        name = (pm.findtext("k:name", "", ns) or "").strip()
        desc = re.sub(r"<[^>]+>", " ", pm.findtext("k:description", "", ns) or "")
        outer = pm.find(".//k:outerBoundaryIs//k:coordinates", ns)
        if outer is None:
            continue
        ring = [(float(c.split(",")[1]), float(c.split(",")[0])) for c in outer.text.split()]
        price = re.search(r"(\d+)\s*kr", desc)
        hours = re.findall(r"(\d{2})(?:[.:]\d{2})?\s*-\s*(\d{2})", desc)
        mx = re.search(r"[Mm]ax\s*(\d+)\s*tim", desc + " " + name)
        code = re.search(r"(?:Områdeskod|Zonkod):?\s*(\d+)", desc)
        color = next((c for c in ("Röd", "Gul", "Blå", "Vit") if c.lower() in name.lower()), "")
        all_days = "alla dagar" in desc.lower()
        wk = [int(hours[0][0]), int(hours[0][1])] if hours else [9, 18]
        pre = [int(hours[1][0]), int(hours[1][1])] if len(hours) > 1 else wk
        zones.append({"n": name, "c": color, "p": int(price.group(1)) if price else None,
                      "wk": wk, "pre": pre, "all": all_days,
                      "max": int(mx.group(1)) if mx else None,
                      "code": code.group(1) if code else None,
                      "ring": ring})
    return zones


def in_ring(lat, lon, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        yi, xi = ring[i]
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def zone_of(lat, lon, zones):
    for i, z in enumerate(zones):
        if in_ring(lat, lon, z["ring"]):
            return i
    return -1


def midpoint(geom):
    return geom[len(geom) // 2] if len(geom) % 2 else (
        ((geom[len(geom) // 2 - 1][0] + geom[len(geom) // 2][0]) / 2,
         (geom[len(geom) // 2 - 1][1] + geom[len(geom) // 2][1]) / 2))


def encode(coords):
    out, plat, plon = [], 0, 0
    for lat, lon in coords:
        a, b = round(lat * 1e5), round(lon * 1e5)
        out += [a - plat, b - plon]
        plat, plon = a, b
    return out


def load_raw(rid, kind):
    path = os.path.join(HERE, "raw", rid, kind + ".json")
    if not os.path.exists(path):
        return None
    return json.load(open(path))


def process_region(region):
    global KX
    rid = region["id"]
    extras = region.get("extras", {})
    streets_raw = load_raw(rid, "streets")
    streets = streets_raw["elements"]
    addrs = load_raw(rid, "addr")["elements"]
    lats = [g["lat"] for e in streets for g in e.get("geometry", [])]
    lons = [g["lon"] for e in streets for g in e.get("geometry", [])]
    KX = 111320 * math.cos(math.radians((min(lats) + max(lats)) / 2))

    # Klipp mot kommungränsen så att grannkommunernas gator inte får den här kommunens regler
    bnd = load_raw(rid, "boundary")
    rings = []
    if bnd:
        polys = [bnd["coordinates"]] if bnd["type"] == "Polygon" else bnd["coordinates"]
        rings = [[(c[1], c[0]) for c in poly[0]] for poly in polys]

    def inside(lat, lon):
        return not rings or any(in_ring(lat, lon, r) for r in rings)

    ways = []
    for e in streets:
        hw = e["tags"].get("highway")
        if hw not in PARKING_HW and hw not in BASE_HW:
            continue
        geom = [(g["lat"], g["lon"]) for g in e["geometry"]]
        if not inside(*midpoint(geom)):
            continue
        ways.append({"id": e["id"], "tags": e["tags"], "hw": hw, "geom": geom,
                     "pts": [xy(*g) for g in geom], "votes": [0, 0],
                     "nums": {1: set(), -1: set()}})

    by_name = defaultdict(list)
    for w in ways:
        if w["hw"] in PARKING_HW and "name" in w["tags"]:
            by_name[norm(w["tags"]["name"])].append(w)

    # Varje adress tilldelas närmaste gatusegment med samma namn
    used = 0
    for a in addrs:
        t = a["tags"]
        m = re.match(r"\d+", t.get("addr:housenumber", ""))
        cands = by_name.get(norm(t.get("addr:street", "")))
        if not m or not cands:
            continue
        c = a.get("center") or {"lat": a.get("lat"), "lon": a.get("lon")}
        if c["lat"] is None:
            continue
        p = xy(c["lat"], c["lon"])
        best = None
        for w in cands:
            d, s = side_info(p, w["pts"])
            if best is None or d < best[0]:
                best = (d, s, w)
        if best[0] > MAX_DIST:
            continue
        n = int(m.group())
        odd = n % 2 == 1
        _, s, w = best
        # röst för "udda sida = vänster" (+1) eller "= höger" (-1)
        w["votes"][0 if (odd and s == 1) or (not odd and s == -1) else 1] += 1
        w["nums"][s].add(n)
        used += 1

    def odd_side(w):
        l, r = w["votes"]
        if l + r == 0:
            return 0
        if l >= 2 * r or (l > r and r == 0):
            return 1
        if r >= 2 * l or (r > l and l == 0):
            return -1
        return 0

    for w in ways:
        w["odd"] = odd_side(w)
        w["src"] = "addr" if w["odd"] else None

    # Sprid till grannsegment med samma namn som saknar adresser
    def key(pt):
        return (round(pt[0], 6), round(pt[1], 6))

    for name, ws in by_name.items():
        ends = defaultdict(list)
        for w in ws:
            ends[key(w["geom"][0])].append((w, "start"))
            ends[key(w["geom"][-1])].append((w, "end"))
        changed = True
        while changed:
            changed = False
            for w in ws:
                if w["odd"]:
                    continue
                for my_end in ("start", "end"):
                    pt = w["geom"][0] if my_end == "start" else w["geom"][-1]
                    for o, o_end in ends[key(pt)]:
                        if o is w or not o["odd"]:
                            continue
                        same_dir = my_end != o_end
                        w["odd"] = o["odd"] if same_dir else -o["odd"]
                        w["src"] = "neighbor"
                        changed = True
                        break
                    if w["odd"]:
                        break

    names, name_idx = [], {}

    def nidx(n):
        if n not in name_idx:
            name_idx[n] = len(names)
            names.append(n)
        return name_idx[n]

    zones = parse_zones(os.path.join(HERE, extras["zones"])) if extras.get("zones") else []

    # Korsningar: noder som delas av flera vägar (utfarter/servicevägar räknas inte).
    # Trafikförordningen 3 kap. 53 §: inte stanna eller parkera inom 10 m från korsande körbana.
    node_ways = defaultdict(set)
    for w in ways:
        if w["hw"] in ("service", "pedestrian"):
            continue
        for g in w["geom"]:
            node_ways[(round(g[0], 7), round(g[1], 7))].add(w["id"])
    way_name = {w["id"]: w["tags"].get("name") for w in ways}
    for w in ways:
        cum, out = 0.0, []
        for i, g in enumerate(w["geom"]):
            if i:
                a, b = w["pts"][i - 1], w["pts"][i]
                cum += math.hypot(b[0] - a[0], b[1] - a[1])
            others = node_ways.get((round(g[0], 7), round(g[1], 7)), set()) - {w["id"]}
            # samma gata som bara fortsätter i nästa OSM-väg är ingen korsning
            if len(others) >= 2 or any(way_name.get(o) != w["tags"].get("name") or not way_name.get(o) for o in others):
                out.append(cum)
        w["junctions"] = out

    # Lokala trafikföreskrifter från Transportstyrelsen, kopplade till gatubitar
    rules = ltf.load(region["kod"], extras.get("forbud"), region.get("lan"), inside if rings else None)
    rules.append({"id": "korsning", "bet": "TrF 3 kap. 53 §", "kind": "nostop", "street": "",
                  "text": "I en korsning och inom 10 meter från närmaste ytterkant av korsande körbana får fordon inte stannas eller parkeras (trafikförordningen 3 kap. 53 §).",
                  "side": None, "sched": None, "unparsed": False, "maxH": None, "maxSched": None, "feeSched": None,
                  "anordnad": False, "for": None, "datum": None, "fee": None, "lines": [], "polys": [], "points": []})
    # Namngivna servicevägar/gågator tas med i kopplingen men ritas bara där en föreskrift
    # uttryckligen tillåter parkering (annars blir varje uppfart och p-gata grön).
    MINOR = {"service", "pedestrian"}
    street_ways = [w for w in ways if (w["hw"] in PARKING_HW or w["hw"] in MINOR) and "name" in w["tags"]]
    pieces = match.match(street_ways, rules, xy, inv, {w["tags"]["name"] for w in street_ways}, junction_rule=len(rules) - 1)
    rule_out, rule_idx = [], {}
    datum = ltf.datum_area(region["kod"], extras.get("datumKml"))
    datum_rings = (datum or {}).get("polys")

    def in_datum(lat, lon):
        if not datum:
            return False
        if datum_rings is None:
            return True  # föreskriften gäller hela området men saknar kartdata
        return any(in_ring(lat, lon, ring) for ring in datum_rings)

    # Tättbebyggt område: kommunens ytor + datumparkeringens område (följer tätortsgränsen där
    # tätorten själv saknar karta i RDT). Saknas allt ritas allt.
    tat_polys, tat_missing = ltf.tatort_polys(region["kod"])
    tat_rings = tat_polys + (datum_rings or [])

    def in_tatort(lat, lon):
        return not tat_rings or any(in_ring(lat, lon, ring) for ring in tat_rings)

    def ridx(i):
        if i not in rule_idx:
            r = rules[i]
            rule_idx[i] = len(rule_out)
            rule_out.append([r["bet"], r["kind"], r["text"], r["sched"], r["unparsed"], r["maxH"],
                             r["for"], r["datum"], r["id"], r["fee"], r["feeSched"], r["maxSched"],
                             r["anordnad"], bool(r.get("fromText"))])
        return rule_idx[i]

    out_streets, out_base = [], []
    allow_idx = {i for i, r in enumerate(rules) if r["kind"] == "allow"}
    for w in ways:
        minor = w["hw"] in MINOR and "name" in w["tags"]
        if (w["hw"] in BASE_HW and not minor) or "name" not in w["tags"]:
            if region.get("base"):
                out_base.append([HW_CODE[w["hw"]], encode(w["geom"])])
            continue
        lf, rf = osm_parking_flags(w["tags"])
        if w["tags"].get("junction") in ("roundabout", "circular"):
            lf = rf = True  # cirkulationsplats = korsning: inte stanna eller parkera
        flags = (1 if lf else 0) | (2 if rf else 0) | (4 if w["src"] == "neighbor" else 0)
        odd_nums = sorted(w["nums"][w["odd"]]) if w["odd"] else []
        even_nums = sorted(w["nums"][-w["odd"]]) if w["odd"] else []
        rng = lambda ns: [ns[0], ns[-1]] if ns else []
        parts = pieces.get(w["id"]) or [{"geom": w["pts"], "left": [], "right": []}]
        jr = len(rules) - 1
        for part in parts:
            geom = [inv(x, y) for x, y in part["geom"]]
            if jr in part["left"] and jr in part["right"]:
                # korsning: ingen parkering på någon sida, ritas bara som bakgrund
                if region.get("base"):
                    out_base.append([HW_CODE[w["hw"]], encode(geom)])
                continue
            if not in_tatort(*midpoint(geom)):
                # utanför tättbebyggt område: parkering bara utanför körbanan, ritas som bakgrund
                if region.get("base"):
                    out_base.append([HW_CODE[w["hw"]], encode(geom)])
                continue
            pflags = flags | (8 if in_datum(*midpoint(geom)) else 0)
            if minor:
                left_ok, right_ok = allow_idx & set(part["left"]), allow_idx & set(part["right"])
                if not (left_ok or right_ok):
                    if region.get("base"):
                        out_base.append([HW_CODE[w["hw"]], encode(geom)])
                    continue
                pflags |= (0 if left_ok else 1) | (0 if right_ok else 2)  # sida utan tillåtelse ritas inte
            out_streets.append([w["id"], nidx(w["tags"]["name"]), HW_CODE[w["hw"]], w["odd"],
                                pflags, rng(odd_nums), rng(even_nums), encode(geom),
                                zone_of(*midpoint(geom), zones),
                                [ridx(i) for i in part["left"]], [ridx(i) for i in part["right"]]])

    # Parkeringsplatser (OSM) som är öppna för allmänheten
    facilities = json.load(open(os.path.join(HERE, extras["facilities"]), encoding="utf-8"))["facilities"] if extras.get("facilities") else []
    lots = []
    for e in (load_raw(rid, "parking") or {"elements": []})["elements"]:
        t = e.get("tags", {})
        if t.get("access") not in ("yes", "permissive"):
            continue
        if t.get("parking") in ("multi-storey", "underground") and t.get("name") and facilities:
            continue  # parkeringshus hanteras i facilities.json
        c = e.get("center") or {"lat": e.get("lat"), "lon": e.get("lon")}
        lat, lon = c["lat"], c["lon"]
        if lat is None or not inside(lat, lon):
            continue
        if any(math.hypot((lat - f["lat"]) * KY, (lon - f["lon"]) * KX) < 80 for f in facilities):
            continue
        fee = t.get("fee")
        fee_code = 1 if fee == "no" else (2 if fee and fee != "no" else 0)
        p = xy(lat, lon)
        near = min(street_ways, key=lambda w: side_info(p, w["pts"])[0])
        cap = re.match(r"\d+", t.get("capacity", ""))
        lots.append([round(lat, 5), round(lon, 5), fee_code, int(cap.group()) if cap else 0,
                     t.get("parking", ""), zone_of(lat, lon, zones), nidx(near["tags"]["name"]),
                     t.get("maxstay", ""), t.get("name", "")])

    water = []
    for e in (load_raw(rid, "base") or {"elements": []})["elements"]:
        t = e.get("tags", {})
        kind = "park" if t.get("leisure") == "park" else ("river" if t.get("waterway") == "river" else "water")
        if e["type"] == "way":
            water.append([kind, encode([(g["lat"], g["lon"]) for g in e["geometry"]])])
        elif e["type"] == "relation":
            for m in e.get("members", []):
                if m.get("role") == "outer" and m.get("geometry"):
                    water.append([kind, encode([(g["lat"], g["lon"]) for g in m["geometry"]])])

    rdt_csv = os.path.join(HERE, "rdt", region["kod"], "export.csv")
    data = {"id": rid, "name": region["name"], "hw": sorted(HW_CODE, key=lambda h: HW_CODE[h]), "names": names,
            "streets": out_streets, "base": out_base, "area": water,
            "zones": [{**{k: v for k, v in z.items() if k != "ring"}, "ring": encode(z["ring"])} for z in zones],
            "lots": lots, "facilities": facilities, "rules": rule_out,
            "datum": {"bet": datum["bet"], "spec": datum["spec"], "text": datum["text"], "exemptAnordnad": datum["exemptAnordnad"]} if datum else None,
            "rdtDate": date.fromtimestamp(os.path.getmtime(rdt_csv)).isoformat(),
            "osmTimestamp": streets_raw["osm3s"]["timestamp_osm_base"]}
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, rid + ".json")
    json.dump(data, open(out, "w"), separators=(",", ":"), ensure_ascii=False)

    known = sum(1 for s in out_streets if s[3])
    matched = {i for p in pieces.values() for part in p for i in part["left"] + part["right"]}
    print(f"[{rid}] adresser {used}/{len(addrs)}, gatubitar {len(out_streets)} ({100 * known / max(1, len(out_streets)):.0f}% känd sida), "
          f"föreskrifter {len(matched)}/{len(rules)} kopplade, p-platser {len(lots)}, "
          f"tätortsytor {len(tat_polys)} (utan karta: {len(tat_missing)}), "
          f"datum {datum['bet'] if datum else '–'}{' (hela kommunen)' if datum and datum_rings is None else ''}, "
          f"{os.path.getsize(out) / 1e6:.2f} MB", flush=True)
    return {"id": rid, "name": region["name"], "bbox": [round(min(lats), 4), round(min(lons), 4), round(max(lats), 4), round(max(lons), 4)],
            "center": center_of(out_streets), "size": os.path.getsize(out),
            "datum": {"bet": datum["bet"], "spec": datum["spec"]} if datum else None}


def center_of(streets):
    """Ungefärligt centrum: där flest gatubitar ligger (tätorten), inte kommunens mittpunkt."""
    cells = defaultdict(int)
    pts = {}
    for s in streets:
        enc = s[7]
        lat, lon = enc[0] / 1e5, enc[1] / 1e5
        k = (round(lat * 50), round(lon * 25))
        cells[k] += 1
        pts[k] = (lat, lon)
    k = max(cells, key=cells.get)
    return [round(pts[k][0], 4), round(pts[k][1], 4)]


def main():
    regions = json.load(open(os.path.join(HERE, "regions.json"), encoding="utf-8"))
    want = set(sys.argv[1:])
    index_path = os.path.join(OUT_DIR, "regions.json")
    index = {r["id"]: r for r in json.load(open(index_path))} if os.path.exists(index_path) else {}
    for reg in regions:
        if want and reg["id"] not in want:
            continue
        if load_raw(reg["id"], "streets") is None or not os.path.exists(os.path.join(HERE, "rdt", reg["kod"], "export.csv")):
            print(f"[{reg['id']}] saknar rådata – kör osm_fetch.py och rdt_fetch.py först")
            continue
        index[reg["id"]] = process_region(reg)
    order = [r["id"] for r in regions]
    json.dump([index[i] for i in order if i in index], open(index_path, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
