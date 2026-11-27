#!/usr/bin/env python3
"""Verify the customer-facing approved FotoMag photo souvenir list and safe assets."""
from html.parser import HTMLParser
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
expected=[
"Футболки с фото","Толстовки и худи","Кепки и бейсболки","Сумки-шопперы",
"Декоративные подушки","Наволочки с фото",
"Кружки классические","Кружки «хамелеон»","Кружки конусные",
"Кружки-молочники","Термокружки","Сувенирные тарелки","Подставки под кружки",
"Магниты на холодильник","Фотомагниты акриловые","Брелоки с фото",
"Значки с фотографией","Карманные зеркальца","Пазлы с фото","Фотокристаллы",
"Фоторамки с фото","Фотокниги","Фотокалендари","Фото на холсте",
"Плакаты и постеры","Коврики для мыши","Чехлы для телефонов",
"Открытки и фотокарточки"]
class Inspector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values=[]
        self.ids=[]
        self.errors=[]
    def handle_starttag(self,tag,attributes):
        a=dict(attributes)
        if tag=="input" and a.get("name")=="gift":
            if a.get("type")!="checkbox":self.errors.append("Non-checkbox gift selector")
            self.values.append(a.get("value"))
        if "id" in a:self.ids.append(a["id"])
        if tag in ("iframe","style","object","embed"):self.errors.append("Unsafe element: "+tag)
        if tag=="script" and a.get("src")!="assets/souvenirs.js":self.errors.append("Unexpected script")
        for k,v in attributes:
            if k.startswith("on") or k=="style":self.errors.append("Inline handler or styling")
html=(ROOT/"souvenirs.html").read_text(encoding="utf-8")
css=(ROOT/"assets/souvenirs.css").read_text(encoding="utf-8")
js=(ROOT/"assets/souvenirs.js").read_text(encoding="utf-8")
p=Inspector();p.feed(html)
errors=list(p.errors)
if p.values!=expected:errors.append("Catalog is not the 28 approved photo-souvenir subcategories in order")
if len(p.ids)!=len(set(p.ids)):errors.append("Duplicate element ids")
for id in ("gift-chosen","gift-note","gift-request-text","gift-copy","gift-email"):
    if id not in p.ids:errors.append("Missing interactive element "+id)
if "Пледы с фото" in html:errors.append("Unapproved category")
if "mailto:kodakprint@yandex.ru" not in html:errors.append("Mailto endpoint changed")
if "https://" in css or "@import" in css:errors.append("Remote CSS or import")
if "innerHTML" in js or "fetch(" in js or "localStorage" in js:errors.append("Unsafe souvenir JS")
if 'src="assets/fotomag_logo_official.svg"' not in html:errors.append("Official logo missing")
if any((ROOT/x).stat().st_size > limit for x,limit in [
("souvenirs.html",16000),("assets/souvenirs.css",7500),("assets/souvenirs.js",4000)]):
    errors.append("Souvenir page exceeds independent size budget")
if errors:
    print("FAIL FotoMag souvenirs:",*errors,sep="\n - ")
    sys.exit(1)
print("PASS FotoMag souvenirs: 28 approved subcategories, safe links and interactions")
