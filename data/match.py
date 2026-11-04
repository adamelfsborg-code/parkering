"""Kopplar lokala trafikföreskrifter (ltf.py) till OSM-gator och delar gatorna i bitar.

Varje gata provas var 3:e meter. En provpunkt omfattas av en föreskrift om föreskriftens
linje ligger nära och löper parallellt med gatan (eller om punkten ligger inne i en
föreskrifts yta). Gatan delas där föreskrifter börjar och slutar, och varje bit får
listor med föreskrifter för vänster respektive höger sida (i OSM-riktningen).
"""
import math
import re

STEP = 3.0
NEAR_NAMED = 15.0     # m, max avstånd föreskriftslinje–gata när gatunamnet stämmer
NEAR_UNNAMED = 9.0    # m, när namnet inte går att para ihop
PARALLEL = 0.85       # |cos| mellan föreskriftslinje och gata
EDGE = 8.0            # m, gränsgator till områden räknas inte in
COMPASS = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}
for a, b in (("NE", "N E"), ("NW", "N W"), ("SE", "S E"), ("SW", "S W")):
    x, y = (sum(COMPASS[c][i] for c in b.split()) / math.sqrt(2) for i in (0, 1))
    COMPASS[a] = (x, y)


def norm(s):
    return re.sub(r"[^a-zåäöé]", "", s.lower().replace("è", "e").replace("é", "e"))


def sample(pts):
    """Provpunkter längs en polylinje: (s, x, y, dx, dy)."""
    out, s = [], 0.0
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L == 0:
            continue
        ux, uy = dx / L, dy / L
        t = 0.0
        while t < L:
            out.append((s + t, a[0] + ux * t, a[1] + uy * t, ux, uy))
            t += STEP
        s += L
    if pts:
        last = pts[-1]
        ux, uy = (out[-1][3], out[-1][4]) if out else (1, 0)
        out.append((s, last[0], last[1], ux, uy))
    return out, s


def seg_near(px, py, segs):
    """Närmaste segment: (avstånd, enhetsvektor)."""
    best = (1e18, (1, 0))
    for (ax, ay, bx, by) in segs:
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        if l2 == 0:
            continue
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
        d = math.hypot(px - ax - t * dx, py - ay - t * dy)
        if d < best[0]:
            L = math.sqrt(l2)
            best = (d, (dx / L, dy / L))
    return best


def in_ring(x, y, ring):
    inside, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def ring_dist(x, y, ring):
    segs = [(a[0], a[1], b[0], b[1]) for a, b in zip(ring, ring[1:] + ring[:1])]
    return seg_near(x, y, segs)[0]


def runs(flags, samples, pad=1.5, min_len=3.0):
    """Sammanhängande sträckor där flags är sanna -> [(s0, s1)]."""
    out, start, prev = [], None, None
    for f, smp in zip(flags, samples):
        if f and start is None:
            start = smp[0]
        if not f and start is not None:
            out.append((start, prev))
            start = None
        prev = smp[0]
    if start is not None:
        out.append((start, prev))
    merged = []
    for a, b in out:
        if merged and a - merged[-1][1] <= 2 * STEP + 0.1:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return [(max(0.0, a - pad), b + pad) for a, b in merged if b - a >= min_len or b == a]


def cut(pts, cum, s0, s1):
    """Del av polylinje mellan längdmått s0 och s1."""
    def at(s):
        for i in range(len(cum) - 1):
            if cum[i + 1] >= s:
                L = cum[i + 1] - cum[i]
                t = 0 if L == 0 else (s - cum[i]) / L
                a, b = pts[i], pts[i + 1]
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        return pts[-1]
    out = [at(s0)]
    for i in range(1, len(pts) - 1):
        if s0 < cum[i] < s1:
            out.append(pts[i])
    out.append(at(s1))
    return out


NAME = r"[A-ZÅÄÖ][\wåäöéè\.\-]*(?: [A-ZÅÄÖa-zåäö][\wåäöéè\.\-]*){0,3}?"
MELLAN = re.compile(r"mellan (" + NAME + r") och (" + NAME + r")(?=,| får| ska|\.| på| enligt| samt|$)")


def synth_lines(rule, by_name, xy):
    """Geometri ur texten för föreskrifter som saknar kartdata i RDT.

    Klarar "på X, västra sidan, mellan A och B ..." (via korsningarna X/A och X/B i OSM)
    och föreskrifter som gäller hela gatan. Sträckor angivna i meter hoppas över.
    """
    text = rule["text"]
    street = norm(rule["street"])
    ways = by_name.get(street) or []
    if not ways or re.search(r"\bmeter\b|punkt|markerad plats|enligt kartbilaga|korsning", text, re.I):
        return []
    m = MELLAN.search(text)
    if not m:
        if re.search(r"\bmellan\b|\bfrån\b|\bvid\b|söder om|norr om|öster om|väster om|parkeringsplats|vändplats|ficka|markerad|anordnad|torget|delen", text, re.I):
            return []
        return [w["geom"] for w in ways]  # hela gatan

    def crossing(other):
        best = None
        for w in ways:
            for o in by_name.get(norm(other), []):
                for p in w["pts"]:
                    for q in o["pts"]:
                        d = math.hypot(p[0] - q[0], p[1] - q[1])
                        if best is None or d < best[0]:
                            best = (d, ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2))
        return best[1] if best and best[0] < 30 else None

    pa, pb = crossing(m.group(1)), crossing(m.group(2))
    if not pa or not pb:
        return []
    cx, cy = pb[0] - pa[0], pb[1] - pa[1]
    L = math.hypot(cx, cy)
    if L < 5:
        return []
    out = []
    for w in ways:
        smp, _ = sample(w["pts"])
        cur = []
        for _, x, y, _, _ in smp:
            t = ((x - pa[0]) * cx + (y - pa[1]) * cy) / (L * L)
            off = abs((x - pa[0]) * cy - (y - pa[1]) * cx) / L
            if -0.02 <= t <= 1.02 and off < max(40.0, 0.3 * L):
                cur.append((x, y))
            elif len(cur) > 1:
                out.append(cur)
                cur = []
            else:
                cur = []
        if len(cur) > 1:
            out.append(cur)
    inv = lambda pts: [(y / 110540, x / (111320 * math.cos(math.radians(60.67)))) for x, y in pts]
    return [inv(o) for o in out]


def match(ways, rules, xy, osm_names):
    """ways: dict med 'pts' (xy), 'tags'. rules: från ltf.load(). Returnerar {way_id: [bitar]}."""
    known = {norm(n) for n in osm_names}
    by_name = {}
    for w in ways:
        by_name.setdefault(norm(w["tags"].get("name", "")), []).append(w)
    synthesized = 0
    for r in rules:
        if not (r["lines"] or r["polys"] or r["points"]):
            r["lines"] = synth_lines(r, by_name, xy)
            r["fromText"] = bool(r["lines"])
            synthesized += bool(r["lines"])
    print(f"placerade från text: {synthesized}")
    prepared = []
    for ri, r in enumerate(rules):
        lines = [[xy(lat, lon) for lat, lon in ln] for ln in r["lines"]]
        polys = [[xy(lat, lon) for lat, lon in pg] for pg in r["polys"]]
        points = [xy(lat, lon) for lat, lon in r["points"]]
        allpts = [p for ln in lines for p in ln] + [p for pg in polys for p in pg] + points
        if not allpts:
            continue
        xs, ys = [p[0] for p in allpts], [p[1] for p in allpts]
        street = norm(r["street"])
        prepared.append({
            "i": ri, "r": r, "segs": [(a[0], a[1], b[0], b[1]) for ln in lines for a, b in zip(ln, ln[1:])],
            "polys": polys, "points": points, "bbox": (min(xs) - 30, min(ys) - 30, max(xs) + 30, max(ys) + 30),
            "street": street, "named": any(k and (k in street) for k in known if len(k) > 4),
        })

    result = {}
    for w in ways:
        pts = w["pts"]
        smp, length = sample(pts)
        if length < 1:
            continue
        wx = [p[0] for p in pts]
        wy = [p[1] for p in pts]
        wb = (min(wx), min(wy), max(wx), max(wy))
        wname = norm(w["tags"].get("name", ""))
        intervals = []  # (s0, s1, rule_index)
        for pr in prepared:
            b = pr["bbox"]
            if b[0] > wb[2] or b[2] < wb[0] or b[1] > wb[3] or b[3] < wb[1]:
                continue
            name_ok = bool(wname) and (wname in pr["street"] or (pr["street"] and pr["street"] in wname))
            if pr["named"] and not name_ok and not pr["polys"]:
                continue  # föreskriften gäller en annan namngiven gata
            near = NEAR_NAMED if name_ok else NEAR_UNNAMED
            if pr["segs"]:
                flags = []
                for s, x, y, ux, uy in smp:
                    d, (vx, vy) = seg_near(x, y, pr["segs"])
                    flags.append(d <= near and abs(ux * vx + uy * vy) >= PARALLEL)
                intervals += [(a, c, pr["i"]) for a, c in runs(flags, smp, min_len=0 if name_ok else 3.0)]
            edge = EDGE if pr["r"]["kind"] == "area_nopark" else -3.0
            for ring in pr["polys"]:
                # stora förbudsområden: gränsgatorna räknas inte in. Små ytor (gångfartsområden,
                # torg): gatan räknas med även om den går precis längs kanten.
                flags = [(in_ring(x, y, ring) and ring_dist(x, y, ring) > edge) or
                         (edge < 0 and ring_dist(x, y, ring) <= -edge) for _, x, y, _, _ in smp]
                intervals += [(a, c, pr["i"]) for a, c in runs(flags, smp, pad=0)]
            for (px, py) in pr["points"]:
                if not name_ok:
                    continue
                best = min(smp, key=lambda q: math.hypot(q[1] - px, q[2] - py))
                if math.hypot(best[1] - px, best[2] - py) <= 25:
                    intervals.append((max(0, best[0] - 10), min(length, best[0] + 10), pr["i"]))
        if not intervals:
            continue

        cuts = sorted({0.0, length, *[min(length, max(0.0, v)) for a, c, _ in intervals for v in (a, c)]})
        clean = [cuts[0]]
        for c in cuts[1:]:
            if c - clean[-1] >= 2.0:
                clean.append(c)
        clean[-1] = length
        cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        pieces = []
        for s0, s1 in zip(clean, clean[1:]):
            mid = (s0 + s1) / 2
            here = sorted({ri for a, c, ri in intervals if a <= mid <= c})
            geom = cut(pts, cum, s0, s1)
            dx, dy = geom[-1][0] - geom[0][0], geom[-1][1] - geom[0][1]
            L = math.hypot(dx, dy) or 1
            nx, ny = -dy / L, dx / L  # vänster normal
            left, right = [], []
            for ri in here:
                side = rules[ri]["side"]
                if side:
                    v = COMPASS[side]
                    dot = nx * v[0] + ny * v[1]
                    if dot > 0.35:
                        left.append(ri)
                        continue
                    if dot < -0.35:
                        right.append(ri)
                        continue
                left.append(ri)
                right.append(ri)
            pieces.append({"geom": geom, "left": left, "right": right})
        result[w["id"]] = pieces
    return result
