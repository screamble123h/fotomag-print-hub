# -*- coding: utf-8 -*-
"""Static release gate for the customer-facing FotoMag mug catalog."""
import json, re, subprocess
from pathlib import Path
R=Path(__file__).resolve().parents[1]
d=json.loads((R/"assets/mug-catalog.json").read_text(encoding="utf-8"))
items=d["items"]; problems=[]
if len(items)!=139:problems.append(f"139 catalogue entries required, got {len(items)}")
skus=[x["sku"] for x in items if x["sku"]]
if len(skus)!=138 or len(set(skus))!=138:problems.append("Supplier SKU count or uniqueness incorrect")
if len({x["series"] for x in items})!=31:problems.append("31 supplier/shop series expected")
for x in items:
 if not x.get("name") or not x.get("series"):problems.append(f"Incomplete title for {x.get('sku')}")
 if x["sku"]:
  p=R/x["image"] if x.get("image") else None
  if not p or not p.is_file():problems.append(f"Missing source photo for {x['sku']}")
  if x["price"] != (1250 if x["sku"]=="10335" else None):problems.append(f"Unverified retail price {x['sku']}")
 else:
  if x["price"]!=650:problems.append("White classic FotoMag price must be 650")
html=(R/"mugs.html").read_text(encoding="utf-8")
js=(R/"assets/mugs.js").read_text(encoding="utf-8")
css=(R/"assets/mugs.css").read_text(encoding="utf-8")
souvenirs=(R/"souvenirs.html").read_text(encoding="utf-8")
if "content-security-policy" not in html.lower():problems.append("Missing content security policy")
for s in ("id=\"photoDialog\"","id=\"forwardBtn\"","id=\"backBtn\"","assets/mugs.js","assets/mug-catalog.json"):
 if s not in html+js:problems.append(f"Missing stage: {s}")
if "object-fit:contain" not in css:problems.append("Mug images may be stretched")
if "mailto:kodakprint@yandex.ru" not in js:problems.append("Missing personal mail destination")
if "mugs.html" not in souvenirs:problems.append("Catalogue not linked from souvenirs")
if souvenirs.count('name="gift"')!=28:problems.append("Approved souvenir list changed")
if any(f'id="gift-group-{i}" open' in souvenirs for i in range(1,5)):problems.append("Souvenir groups should start collapsed")
if "закупочная" in html.lower() or "price_from_supplier" in js:problems.append("Wholesale pricing exposed")
if problems:raise SystemExit("FAIL FotoMag mugs:\n - "+"\n - ".join(problems))
subprocess.run(["node", str(R/"scripts/test_mug_order.cjs")], check=True)
print("PASS 139 mugs, 31 original series, 138 local supplier photos, no wholesale prices, mug ordering links")
