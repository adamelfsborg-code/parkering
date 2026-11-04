"""Bygger kompakt gatudata för Gävle från OpenStreetMap-exporter.

Indata: streets.json, addr.json, (valfritt) base.json från Overpass.
Utdata: ../build/gavle-data.json

För varje gata räknas ut vilken sida (vänster/höger i ritriktningen) som har
udda husnummer, genom att projicera adresspunkter med samma gatunamn på gatan.
"""
import json
import math
import os
import re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "build", "gavle-data.json")

PARKING_HW = {"primary", "secondary", "tertiary", "unclassified", "residential",
              "living_street", "road"}
# Vägtyper som ritas som bakgrund (ej klickbara)
BASE_HW = {"service", "motorway", "motorway_link", "trunk", "trunk_link",
           "primary_link", "secondary_link", "tertiary_link", "pedestrian"}
HW_CODE = {h: i for i, h in enumerate(sorted(PARKING_HW | BASE_HW))}

LAT0 = 60.67
KX = 111320 * math.cos(math.radians(LAT0))
KY = 110540
MAX_DIST = 70  # m, adress -> gata


def xy(lat, lon):
    return (lon * KX, lat * KY)


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


def main():
    streets = json.load(open(os.path.join(HERE, "streets.json")))["elements"]
    addrs = json.load(open(os.path.join(HERE, "addr.json")))["elements"]

    ways = []
    for e in streets:
        hw = e["tags"].get("highway")
        if hw not in PARKING_HW and hw not in BASE_HW:
            continue
        geom = [(g["lat"], g["lon"]) for g in e["geometry"]]
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

    zones = parse_zones(os.path.join(HERE, "zones.kml"))
    out_streets, out_base = [], []
    for w in ways:
        if w["hw"] in BASE_HW or "name" not in w["tags"]:
            out_base.append([HW_CODE[w["hw"]], encode(w["geom"])])
            continue
        lf, rf = osm_parking_flags(w["tags"])
        flags = (1 if lf else 0) | (2 if rf else 0) | (4 if w["src"] == "neighbor" else 0)
        odd_nums = sorted(w["nums"][w["odd"]]) if w["odd"] else []
        even_nums = sorted(w["nums"][-w["odd"]]) if w["odd"] else []
        rng = lambda ns: [ns[0], ns[-1]] if ns else []
        out_streets.append([w["id"], nidx(w["tags"]["name"]), HW_CODE[w["hw"]], w["odd"],
                            flags, rng(odd_nums), rng(even_nums), encode(w["geom"]),
                            zone_of(*midpoint(w["geom"]), zones)])


    # Parkeringsplatser (OSM) som är öppna för allmänheten
    facilities = json.load(open(os.path.join(HERE, "facilities.json"), encoding="utf-8"))["facilities"]
    named_streets = [w for w in ways if w["hw"] in PARKING_HW and "name" in w["tags"]]
    lots = []
    for e in json.load(open(os.path.join(HERE, "parking.json")))["elements"]:
        t = e.get("tags", {})
        if t.get("access") not in ("yes", "permissive"):
            continue
        if t.get("parking") in ("multi-storey", "underground") and t.get("name"):
            continue  # parkeringshus hanteras i facilities.json
        c = e.get("center") or {"lat": e.get("lat"), "lon": e.get("lon")}
        lat, lon = c["lat"], c["lon"]
        if any(math.hypot((lat - f["lat"]) * KY, (lon - f["lon"]) * KX) < 80 for f in facilities):
            continue
        fee = t.get("fee")
        fee_code = 1 if fee == "no" else (2 if fee and fee != "no" else 0)
        p = xy(lat, lon)
        near = min(named_streets, key=lambda w: side_info(p, w["pts"])[0])
        cap = re.match(r"\d+", t.get("capacity", ""))
        lots.append([round(lat, 5), round(lon, 5), fee_code, int(cap.group()) if cap else 0,
                     t.get("parking", ""), zone_of(lat, lon, zones), nidx(near["tags"]["name"]),
                     t.get("maxstay", ""), t.get("name", "")])

    water = []
    base_path = os.path.join(HERE, "base.json")
    try:
        for e in json.load(open(base_path))["elements"]:
            t = e.get("tags", {})
            kind = "park" if t.get("leisure") == "park" else (
                "river" if t.get("waterway") == "river" else (
                    "coast" if t.get("natural") == "coastline" else "water"))
            if e["type"] == "way":
                water.append([kind, encode([(g["lat"], g["lon"]) for g in e["geometry"]])])
            elif e["type"] == "relation":
                for m in e.get("members", []):
                    if m.get("role") == "outer" and m.get("geometry"):
                        water.append([kind, encode([(g["lat"], g["lon"]) for g in m["geometry"]])])
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        print("base.json saknas eller är trasig – ritar utan vatten/parker")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    data = {"hw": sorted(HW_CODE, key=lambda h: HW_CODE[h]), "names": names,
            "streets": out_streets, "base": out_base, "area": water,
            "zones": [{**{k: v for k, v in z.items() if k != "ring"}, "ring": encode(z["ring"])} for z in zones],
            "lots": lots, "facilities": facilities,
            "osmTimestamp": json.load(open(os.path.join(HERE, "streets.json")))["osm3s"]["timestamp_osm_base"]}
    json.dump(data, open(OUT, "w"), separators=(",", ":"), ensure_ascii=False)

    known = sum(1 for s in out_streets if s[3])
    print(f"adresser använda: {used}/{len(addrs)}")
    print(f"gatusegment: {len(out_streets)}, med känd udda sida: {known} "
          f"({100 * known / max(1, len(out_streets)):.0f}%), bakgrund: {len(out_base)}, ytor: {len(water)}")
    print(f"zoner: {len(zones)}, gator i zon: {sum(1 for x in out_streets if x[8] >= 0)}, p-platser: {len(lots)}, anläggningar: {len(facilities)}")
    print(f"storlek: {os.path.getsize(OUT) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
