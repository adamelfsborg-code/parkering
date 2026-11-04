"""Bygger sidan i två varianter.

docs/            – GitHub Pages: bakgrundskarta och position. Data per kommun i docs/data/<id>.json,
                   laddas när kartan visar kommunen.
build/index.html – Claude-artifact: all data inbakad i sidan, egen vektorbakgrund, ingen position.
"""
import json
import os
import shutil
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = "https://github.com/adamelfsborg-code/datumparkering-gavle"
SITE = "https://adamelfsborg-code.github.io/datumparkering-gavle/"
DATA = os.path.join(ROOT, "build", "data")


def read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


tpl = read("src", "template.html")
css = read("src", "leaflet.min.css")
rules_js = read("src", "rules.js")
app_js = read("src", "app.js")
index = json.load(open(os.path.join(DATA, "regions.json"), encoding="utf-8"))
region_data = {r["id"]: read("build", "data", r["id"] + ".json") for r in index}
metas = [json.loads(region_data[r["id"]]) for r in index]
osm_date = min(datetime.fromisoformat(m["osmTimestamp"].replace("Z", "+00:00")) for m in metas).strftime("%Y-%m-%d")
rdt_date = min(m["rdtDate"] for m in metas)
version = datetime.now().strftime("%Y%m%d%H%M")


def page(tiles, inline):
    cfg = json.dumps({"tiles": tiles, "site": SITE, "repo": REPO, "regions": index, "version": version}, ensure_ascii=False)
    data = "{" + ",".join(f'"{k}":{v}' for k, v in region_data.items()) + "}" if inline else "null"
    return (tpl.replace("/*LEAFLET_CSS*/", css)
               .replace("/*CONFIG*/", cfg.replace("</", "<\\/"))
               .replace("/*DATA*/", data.replace("</", "<\\/"))
               .replace("/*RULES_JS*/", rules_js)
               .replace("/*APP_JS*/", app_js)
               .replace("__OSMDATE__", osm_date)
               .replace("__RDTDATE__", rdt_date)
               .replace("__REPO__", REPO)
               .replace("__SITE__", SITE))


def write(path, html):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(html)
    print(f"{os.path.relpath(path, ROOT)}: {os.path.getsize(path) / 1e6:.2f} MB")


write(os.path.join(ROOT, "docs", "index.html"), page(True, False))
shutil.rmtree(os.path.join(ROOT, "docs", "data"), ignore_errors=True)
os.makedirs(os.path.join(ROOT, "docs", "data"))
for r in index:
    # Bakgrundsgeometri behövs bara i Claude-versionen (GitHub-versionen har riktig karta)
    d = json.loads(region_data[r["id"]])
    d["base"], d["area"] = [], []
    json.dump(d, open(os.path.join(ROOT, "docs", "data", r["id"] + ".json"), "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
print(f"docs/data: {len(index)} kommuner, {sum(os.path.getsize(os.path.join(ROOT, 'docs', 'data', r['id'] + '.json')) for r in index) / 1e6:.2f} MB")
write(os.path.join(ROOT, "build", "index.html"), page(False, True))
