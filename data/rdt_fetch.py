"""Hämtar en kommuns gällande lokala trafikföreskrifter (LTF) från Transportstyrelsens RDT.

    python3 data/rdt_fetch.py 2180          # en kommun (beteckningskod, t.ex. 2180 = Gävle)
    python3 data/rdt_fetch.py --all         # alla kommuner i data/regions.json

För varje föreskrift som rör parkering/stannande/huvudled m.m. sparas:
  data/rdt/<kod>/geo/<id>.json  – geometrin (GeoJSON, SWEREF99 TM) från föreskriftens kartflik
  data/rdt/<kod>/txt/<id>.txt   – föreskriftens text (pdftotext av PDF:en)
samt hela listan i data/rdt/<kod>/export.csv. Redan hämtade filer hoppas över.

Kräver pdftotext (poppler).
"""
import csv
import html
import io
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import http.cookiejar
from concurrent.futures import ThreadPoolExecutor
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
RDT_ROOT = os.path.join(HERE, "rdt")
BASE = "https://rdt.transportstyrelsen.se/rdt/"
UA = "parking-assistance-gavle/0.2 (personlig app för datumparkering i Gävle)"

RELEVANT = re.compile(r"parker|stanna|huvudled|gångfart|gågata|ändamålsplats|laddplats|rörelsehindrade|lastplats|på- och avstigning|tättbebyggt", re.I)


def opener():
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    op.addheaders = [("User-Agent", UA)]
    return op


def form_fields(page):
    d = {}
    for m in re.finditer(r"<input[^>]*>", page):
        t = m.group(0)
        n, v, ty = (re.search(p, t) for p in (r'name="([^"]+)"', r'value="([^"]*)"', r'type="([^"]+)"'))
        if n and (not ty or ty.group(1) not in ("submit", "checkbox", "radio", "image")):
            d[n.group(1)] = html.unescape(v.group(1)) if v else ""
    return d


def export_list(kod, out):
    op = opener()
    page = op.open(BASE + "AF06_Search.aspx?UseStfs=1").read().decode("utf-8", "replace")
    d = form_fields(page)
    p = "ctl00$ContentPlaceHolder1$ucAF06Search$"
    d[p + "txtESPBeteckningKod"] = kod
    d[p + "txtESPEndastGallandeDen"] = date.today().isoformat()
    d[p + "btnSokOchExportera"] = "x"
    body = op.open(BASE + "AF06_Search.aspx?UseStfs=1", urllib.parse.urlencode(d).encode()).read()
    text = body.decode("utf-8-sig")
    if not text.startswith("Beslutsmyndighet;"):
        sys.exit("Exporten från RDT såg inte ut som väntat")
    open(os.path.join(out, "export.csv"), "w", encoding="utf-8").write(text)
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def fetch_one(row, out):
    fid = row["Länk till föreskrift"].split("ForeskriftId=")[1]
    geo_path = os.path.join(out, "geo", fid + ".json")
    txt_path = os.path.join(out, "txt", fid + ".txt")
    err = None
    op = opener()
    for attempt in range(3):
        try:
            if not os.path.exists(geo_path):
                page = op.open(BASE + f"AF06_View.aspx?ForeskriftId={fid}&map=1", timeout=60).read().decode("utf-8", "replace")
                m = re.search(r"Register\.init\('[^']+',\s*'(.*?)'\s*[,)]", page, re.S)
                open(geo_path, "w", encoding="utf-8").write(m.group(1) if m else "{}")
            if not os.path.exists(txt_path):
                pdf = op.open(BASE + f"AF06_ViewDocument.aspx?ForeskriftId={fid}&NoNavigation=1", timeout=60).read()
                txt = subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf, capture_output=True).stdout.decode("utf-8", "replace")
                open(txt_path, "w", encoding="utf-8").write(txt)
            return None
        except Exception as e:  # nätverksfel: försök igen
            err = e
            time.sleep(2 + attempt * 3)
    return f"{row['Beteckning']}: {err}"


def fetch_kommun(kod):
    out = os.path.join(RDT_ROOT, kod)
    os.makedirs(os.path.join(out, "geo"), exist_ok=True)
    os.makedirs(os.path.join(out, "txt"), exist_ok=True)
    rows = export_list(kod, out)
    todo = [r for r in rows if RELEVANT.search(r["Rubrik"])]
    print(f"[{kod}] {len(rows)} gällande föreskrifter, {len(todo)} rör parkering/stannande", flush=True)
    done = 0
    errors = []
    with ThreadPoolExecutor(4) as ex:
        for res in ex.map(lambda r: fetch_one(r, out), todo):
            done += 1
            if res:
                errors.append(res)
            if done % 200 == 0:
                print(f"[{kod}] {done}/{len(todo)}", flush=True)
    print(f"[{kod}] klart: {done}, fel: {len(errors)}", flush=True)
    for e in errors:
        print("FEL", e)


if __name__ == "__main__":
    import json
    if sys.argv[1:] == ["--all"]:
        regions = json.load(open(os.path.join(HERE, "regions.json"), encoding="utf-8"))
        for reg in regions:
            fetch_kommun(reg["kod"])
    else:
        for kod in sys.argv[1:]:
            fetch_kommun(kod)
