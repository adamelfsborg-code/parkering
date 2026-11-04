"""Granskar byggd data: letar efter gatusidor som troligen ritas fel.

    python3 data/audit.py gavle

Kontroller:
  1. Ritade sidor utan föreskrifter inne i/intill en zon med parkeringsförbud.
  2. Föreskrifter med exakt geometri i RDT som kopplats till mycket kortare eller längre gatusträcka.
  3. Ritade sidor på rondeller.
  4. Stora vägar (primary/secondary) utan några föreskrifter – kan vara statliga vägar vars
     regler beslutas av länsstyrelsen och inte finns i kommunens föreskrifter.
  5. Föreskrifter som placerats utifrån text (osäker placering).
"""
import json
import math
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ltf  # noqa: E402

BANS = {"nostop", "nopark", "reserved", "pedestrian"}


def decode(a):
    out, la, lo = [], 0, 0
    for i in range(0, len(a), 2):
        la += a[i]
        lo += a[i + 1]
        out.append((la / 1e5, lo / 1e5))
    return out


def length(g):
    kx = 111320 * math.cos(math.radians(g[0][0]))
    return sum(math.hypot((b[0] - a[0]) * 110540, (b[1] - a[1]) * kx) for a, b in zip(g, g[1:]))


def never_allowed(d, s, left):
    hw = d["hw"][s[2]]
    rs = [d["rules"][i] for i in (s[9] if left else s[10])]
    allows = any(r[1] == "allow" for r in rs)
    if s[4] & (1 if left else 2):
        return True
    if hw == "living_street" and not allows:
        return True
    return any((r[1] in BANS and not (r[3] and not r[4])) or (r[1] in ("mainroad", "area_nopark") and not allows) for r in rs)


def main(rid):
    regions = {r["id"]: r for r in json.load(open(os.path.join(HERE, "regions.json"), encoding="utf-8"))}
    reg = regions[rid]
    d = json.load(open(os.path.join(HERE, "..", "build", "data", rid + ".json")))
    raw = {e["id"]: e["tags"] for e in json.load(open(os.path.join(HERE, "raw", rid, "streets.json")))["elements"]}
    rules = ltf.load(reg["kod"], reg.get("extras", {}).get("forbud"))
    by_id = {r["id"]: r for r in rules}

    drawn_len = 0
    zone_free, roundabout, big_free = Counter(), 0, Counter()
    matched = Counter()
    zone_rings = [r["polys"][0] for r in rules if r["kind"] == "area_nopark" and r["polys"]]

    def near_zone(lat, lon):
        kx = 111320 * math.cos(math.radians(lat))
        for ring in zone_rings:
            inside, j = False, len(ring) - 1
            for i in range(len(ring)):
                yi, xi = ring[i]
                yj, xj = ring[j]
                if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                    inside = not inside
                j = i
            if inside or min(math.hypot((p[0] - lat) * 110540, (p[1] - lon) * kx) for p in ring) < 30:
                return True
        return False

    for s in d["streets"]:
        g = decode(s[7])
        L = length(g)
        name = d["names"][s[1]]
        for rid_ in {d["rules"][i][8] for i in s[9] + s[10]}:
            matched[rid_] += L  # sträckan räknas en gång oavsett sida
        for left in (True, False):
            idx = s[9] if left else s[10]
            if never_allowed(d, s, left):
                continue
            drawn_len += L
            tags = raw.get(s[0], {})
            if tags.get("junction") in ("roundabout", "circular"):
                roundabout += 1
            if not idx and zone_rings and near_zone(*g[len(g) // 2]):
                zone_free[name] += L
            if not idx and d["hw"][s[2]] in ("primary", "secondary"):
                big_free[name] += L

    print(f"== {reg['name']}: {len(d['streets'])} gatubitar, {drawn_len / 1000:.1f} km ritade sidor")
    print(f"\n1. Ritade sidor utan föreskrift i/intill förbudszon: {sum(zone_free.values()):.0f} m på {len(zone_free)} gator")
    for n, l in zone_free.most_common(25):
        print(f"   {n}: {l:.0f} m")

    print("\n2. Föreskrifter med exakt geometri som inte täcks av ritade/kopplade gatubitar:")
    # andel av föreskriftens geometripunkter som har en gatubit med föreskriften inom 20 m
    pieces_by_rule = {}
    for s_ in d["streets"]:
        g = decode(s_[7])
        for i in set(s_[9] + s_[10]):
            pieces_by_rule.setdefault(d["rules"][i][8], []).append(g)
    near_any = lambda p, gs: any(min(math.hypot((q[0] - p[0]) * 110540, (q[1] - p[1]) * 111320 * math.cos(math.radians(p[0]))) for q in g) < 20 for g in gs)
    bad = []
    for r in rules:
        if not r["lines"] or r["kind"] == "area_nopark":
            continue
        pts = [p for ln in r["lines"] for p in ln[:: max(1, len(ln) // 10)]]
        gs = pieces_by_rule.get(r["id"], [])
        cov = sum(near_any(p, gs) for p in pts) / len(pts)
        if cov < 0.6:
            bad.append((cov, r["bet"], r["kind"], r["street"]))
    print(f"   {len(bad)} av {sum(1 for r in rules if r['lines'] and r['kind'] != 'area_nopark')} föreskrifter med linjegeometri har < 60 % täckning")
    for cov, bet, kind, street in sorted(bad)[:30]:
        print(f"   {bet} {kind:9} {street[:34]:34} täckning {cov:4.0%}")

    print(f"\n3. Ritade sidor på rondeller: {roundabout}")
    print(f"\n4. Stora vägar utan föreskrifter (kan vara statliga vägar): {sum(big_free.values()) / 1000:.1f} km")
    for n, l in big_free.most_common(12):
        print(f"   {n}: {l:.0f} m")
    text_placed = [r for r in d["rules"] if r[13]]
    print(f"\n5. Placerade från text (osäkra): {len(text_placed)} – {dict(Counter(r[1] for r in text_placed))}")


if __name__ == "__main__":
    for rid in sys.argv[1:] or ["gavle"]:
        main(rid)
