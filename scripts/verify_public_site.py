#!/usr/bin/env python3
"""Zero-dependency allowlist for FotoMag public static landing page."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import json,re,sys
ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/"index.html"
html=FILE.read_text(encoding="utf-8")
css=(ROOT/"assets/site-v4.css").read_text(encoding="utf-8")
js=(ROOT/"assets/site-v4.js").read_text(encoding="utf-8")
required={
 "bot-vk":"https://vk.com/write-20848548",
 "bot-max":"https://max.ru/id180904019369_bot",
 "bot-tg":"https://t.me/fotomag_orders_bot",
 "direct-vk":"https://vk.com/write103477713",
 "direct-tg":"https://t.me/Gug18aa",
 "direct-max":"https://max.ru/u/f9LHodD0cOJ4xQH5eXwmG7FE-sm42CyZd4DzqF_2BbIDG9GFNtKI4fbc5LU",
 "store-photo-map":"https://yandex.com/maps/org/fotomag/1005628718/?lang=ru",
 "map-route":"https://yandex.com/maps/org/fotomag/1005628718/?lang=ru",
}
allowed_hosts={"vk.com","vk.ru","t.me","max.ru","yandex.com","kantstovary-dlja-shkoly-i.clients.site"}
errors=[]
class Analyzer(HTMLParser):
 def __init__(self):super().__init__();self.ids={};self.links=[];self.scripts=[];self.styles=[];self.forms=0;self.meta={};self.references=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if "id" in a:
   if a["id"] in self.ids:errors.append("Duplicate ID "+a["id"])
   self.ids[a["id"]]=a
  for k,v in attrs:
   if k and k.lower().startswith("on"):errors.append("Inline event handler")
   if k=="style":errors.append("Inline style attribute")
  if tag in ("form","iframe","object","embed","base"):errors.append("Unexpected HTML tag: "+tag)
  if tag=="script":
   self.scripts.append(a)
   if not (a.get("src")=="assets/site-v4.js" or (a.get("type")=="application/ld+json" and not a.get("src"))):
    errors.append("Unexpected script")
  if tag=="style":errors.append("Inline style tag")
  if tag=="link":self.references.append(a)
  if tag=="a":
   self.links.append(a)
   href=a.get("href","")
   if href.startswith("#"):pass
   elif href.startswith("tel:"):
    if href!="tel:+79124665090":errors.append("Unexpected telephone target")
   elif href.startswith("mailto:"):
    if not href.startswith("mailto:kodakprint@yandex.ru"):errors.append("Unexpected mail target")
   else:
    u=urlsplit(href)
    if u.scheme!="https" or u.hostname not in allowed_hosts or u.username or u.password:errors.append("Unexpected external domain or protocol")
    if a.get("target")=="_blank" and not ("noopener" in a.get("rel","") and "noreferrer" in a.get("rel","")):errors.append("Unsafe target blank")
  if tag=="meta" and a.get("http-equiv"):self.meta[a["http-equiv"].lower()]=a.get("content")
a=Analyzer();a.feed(html)
for key,url in required.items():
 if a.ids.get(key,{}).get("href")!=url:errors.append("Critical link mismatch: "+key)
if "class=\"order__phone\"" not in html:errors.append("Visible telephone missing")
if html.count('href="#bots"')<4:errors.append("Service selection links missing")
if html.count('<meta name="referrer" content="no-referrer">')!=1:errors.append("Referrer policy missing")
if html.count('<link rel="icon"')!=1:errors.append("Favicon missing")
if not any(x.get("href")=="site.webmanifest" for x in a.references):errors.append("Manifest missing")
csp=a.meta.get("content-security-policy","")
for must in ("default-src 'none'","script-src 'self'","style-src 'self'","object-src 'none'","form-action 'none'","base-uri 'none'","connect-src 'none'"):
 if must not in csp:errors.append("CSP missing "+must)
if "unsafe-inline" in csp or "unsafe-eval" in csp:errors.append("Unsafe CSP keyword")
if len(a.scripts)!=2 or any(s.get("src") not in (None,"assets/site-v4.js") for s in a.scripts):errors.append("Unexpected script count")
if any(term in js for term in ("eval(","new Function(","document.write(","innerHTML","XMLHttpRequest","localStorage","sessionStorage")):errors.append("Unsafe client JavaScript capability")
if "url(\"assets/" in css:errors.append("Wrong font path in external CSS")
for asset in ("assets/fotomag_logo_official.svg","assets/FotoMag_FACADE_APPROVED_web.webp","assets/manrope-cyrillic.woff2","assets/manrope-latin.woff2","assets/site-v4.css","assets/site-v4.js"):
 if not (ROOT/asset).is_file():errors.append("Required asset missing: "+asset)
manifest=json.loads((ROOT/"site.webmanifest").read_text(encoding="utf-8"))
if manifest.get("start_url")!="./" or manifest.get("scope")!="./":errors.append("Manifest scope unexpected")
if any(not (ROOT/i.get("src","")).is_file() for i in manifest.get("icons",[])):errors.append("Manifest icons missing")
# Never emit actual suspected sensitive values into logs.
for p in (ROOT/"index.html",ROOT/"assets/site-v4.js",ROOT/"assets/site-v4.css",ROOT/"README.md"):
 data=p.read_text(encoding="utf-8",errors="ignore")
 if re.search(r'ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{80,}|AKIA[0-9A-Z]{16}|-----BEGIN (RSA )?PRIVATE KEY-----',data):
  errors.append("Potential embedded credential in "+p.name)
if errors:
 print("FAILED FotoMag security guardrails:\n"+"\n".join("- "+e for e in errors))
 sys.exit(1)
print("PASS: FotoMag link allowlist, CSP, asset integrity, safe client code and release manifest.")
