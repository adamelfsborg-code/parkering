"""Hämtar OpenStreetMap-data per kommun via Overpass.

    python3 data/osm_fetch.py gavle sandviken   # vissa regioner (id i regions.json)
    python3 data/osm_fetch.py --all

Sparar data/raw/<id>/{streets,addr,parking}.json (och base.json för regioner med "base": true,
som behövs för Claude-versionen utan bakgrundskarta).
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "parking-assistance/0.3 (personlig parkeringsapp)"
SERVERS = ["https://overpass-api.de/api/interpreter"]  # speglarna svarar ofta inte

HIGHWAYS = "primary|secondary|tertiary|unclassified|residential|living_street|service|pedestrian|trunk|motorway|primary_link|secondary_link|tertiary_link|trunk_link|motorway_link|road"

# Rektangelfrågor (snabbare än kommunytor i Overpass); process.py klipper mot kommungränsen.
QUERIES = {
    "streets": '[out:json][timeout:300];way["highway"~"^({hw})$"]({bbox});out tags geom;',
    "addr": '[out:json][timeout:300];(node["addr:housenumber"]["addr:street"]({bbox});way["addr:housenumber"]["addr:street"]({bbox}););out tags center;',
    "parking": '[out:json][timeout:300];nwr["amenity"="parking"]({bbox});out tags center;',
    "base": '[out:json][timeout:300];(way["natural"="water"]({bbox});relation["natural"="water"]({bbox});way["waterway"="riverbank"]({bbox});'
            'way["waterway"="river"]({bbox});way["leisure"="park"]({bbox}););out tags geom;',
}


def boundary(region, out):
    """Kommungränsen (GeoJSON) från Nominatim, sparas i boundary.json."""
    path = os.path.join(out, "boundary.json")
    if not os.path.exists(path):
        q = urllib.parse.urlencode({"q": region["kommun"] + ", Sverige", "format": "json", "polygon_geojson": 1,
                                    "polygon_threshold": 0.0005, "limit": 5})
        req = urllib.request.Request("https://nominatim.openstreetmap.org/search?" + q, headers={"User-Agent": UA})
        hits = json.loads(urllib.request.urlopen(req, timeout=60).read())
        hits = [h for h in hits if h.get("geojson", {}).get("type") in ("Polygon", "MultiPolygon")]
        if not hits:
            raise RuntimeError(f"hittade ingen kommungräns för {region['kommun']}")
        json.dump(hits[0]["geojson"], open(path, "w"))
        time.sleep(1.1)
    g = json.load(open(path))
    rings = [g["coordinates"][0]] if g["type"] == "Polygon" else [p[0] for p in g["coordinates"]]
    lats = [c[1] for r in rings for c in r]
    lons = [c[0] for r in rings for c in r]
    return f"{min(lats):.4f},{min(lons):.4f},{max(lats):.4f},{max(lons):.4f}"


def run(query):
    last = None
    for attempt in range(6):
        url = SERVERS[attempt % len(SERVERS)]
        try:
            req = urllib.request.Request(url, urllib.parse.urlencode({"data": query}).encode(), headers={"User-Agent": UA})
            body = urllib.request.urlopen(req, timeout=330).read()
            data = json.loads(body)
            if "elements" in data and not data.get("remark", "").startswith("runtime error"):
                return body
            last = data.get("remark")
        except Exception as e:  # överbelastad server: vänta och försök igen
            last = e
        time.sleep(15 + attempt * 15)
    raise RuntimeError(f"Overpass misslyckades: {last}")


def fetch(region):
    out = os.path.join(HERE, "raw", region["id"])
    os.makedirs(out, exist_ok=True)
    bbox = boundary(region, out)
    kinds = ["streets", "addr", "parking"] + (["base"] if region.get("base") else [])
    for kind in kinds:
        path = os.path.join(out, kind + ".json")
        if os.path.exists(path):
            continue
        body = run(QUERIES[kind].format(bbox=bbox, hw=HIGHWAYS))
        open(path, "wb").write(body)
        print(f"[{region['id']}] {kind}: {len(json.loads(body)['elements'])} objekt", flush=True)


if __name__ == "__main__":
    regions = json.load(open(os.path.join(HERE, "regions.json"), encoding="utf-8"))
    ids = None if sys.argv[1:] == ["--all"] else set(sys.argv[1:])
    for reg in regions:
        if ids is None or reg["id"] in ids:
            fetch(reg)
