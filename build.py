"""Bygger sidan i två varianter.

docs/index.html  – GitHub Pages: bakgrundskarta (CARTO/OSM) och position.
build/index.html – Claude-artifact: egen vektorbakgrund, ingen position (blockeras där).
"""
import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = "https://github.com/adamelfsborg-code/datumparkering-gavle"
SITE = "https://adamelfsborg-code.github.io/datumparkering-gavle/"


def read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


tpl = read("src", "template.html")
css = read("src", "leaflet.min.css")
rules_js = read("src", "rules.js")
app_js = read("src", "app.js")
data = read("build", "gavle-data.json")
meta = json.loads(data)
osm_date = datetime.fromisoformat(meta["osmTimestamp"].replace("Z", "+00:00")).strftime("%Y-%m-%d")
rdt_date = meta.get("rdtDate", "")

for out, tiles in ((os.path.join("docs", "index.html"), True), (os.path.join("build", "index.html"), False)):
    cfg = json.dumps({"tiles": tiles, "site": SITE, "repo": REPO})
    html = (tpl.replace("/*LEAFLET_CSS*/", css)
               .replace("/*CONFIG*/", cfg)
               .replace("/*DATA*/", data.replace("</", "<\\/"))
               .replace("/*RULES_JS*/", rules_js)
               .replace("/*APP_JS*/", app_js)
               .replace("__OSMDATE__", osm_date)
               .replace("__RDTDATE__", rdt_date)
               .replace("__REPO__", REPO)
               .replace("__SITE__", SITE))
    path = os.path.join(ROOT, out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(html)
    print(f"{out}: {os.path.getsize(path) / 1e6:.2f} MB")
