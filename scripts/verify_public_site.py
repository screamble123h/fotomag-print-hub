#!/usr/bin/env python3
"""FotoMag public smartphone release gate — no network and no third-party dependencies."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit
import json,re,sys
ROOT=Path(__file__).resolve().parents[1]
HTML=ROOT/'index.html'
CSS=ROOT/'assets/app-shell.css'
JS=ROOT/'assets/app-shell.js'
errors=[]
for f in (HTML,CSS,JS,ROOT/'assets/fotomag_logo_official.svg',ROOT/'assets/FotoMag_FACADE_APPROVED_web.webp',ROOT/'site.webmanifest'):
    if not f.exists():errors.append('Required asset missing: '+str(f.relative_to(ROOT)))
if errors:
    print('\n'.join(errors));sys.exit(1)
html=HTML.read_text(encoding='utf-8')
css=CSS.read_text(encoding='utf-8')
js=JS.read_text(encoding='utf-8')
allowed_hosts={'vk.com','t.me','max.ru','yandex.com','kantstovary-dlja-shkoly-i.clients.site'}
required_links={
 'bot-vk':'https://vk.com/write-20848548',
 'bot-max':'https://max.ru/id180904019369_bot',
 'bot-tg':'https://t.me/fotomag_orders_bot',
 'direct-vk':'https://vk.com/write103477713',
 'direct-max':'https://max.ru/u/f9LHodD0cOJ4xQH5eXwmG7FE-sm42CyZd4DzqF_2BbIDG9GFNtKI4fbc5LU',
 'direct-email':'mailto:kodakprint@yandex.ru?subject=FotoMag%20%E2%80%94%20%D0%BB%D0%B8%D1%87%D0%BD%D0%BE%D0%B5%20%D1%81%D0%BE%D0%BE%D0%B1%D1%89%D0%B5%D0%BD%D0%B8%D0%B5',
 'direct-tg':'https://t.me/Gug18aa',
 'map-route':'https://yandex.com/maps/org/fotomag/1005628718/?lang=ru',
 'store-photo-map':'https://yandex.com/maps/org/fotomag/1005628718/?lang=ru',
 'quick-bot-vk':'https://vk.com/write-20848548',
 'quick-bot-max':'https://max.ru/id180904019369_bot',
 'quick-bot-tg':'https://t.me/fotomag_orders_bot',
}
class Auditor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links=[];self.buttons=[];self.scripts=[];self.templates=[];self.meta={};self.css=[];self.images=[];self.h1=0;self.main=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        for name,value in attrs:
            if name.lower().startswith('on'):errors.append('Inline event handler: '+str(name))
            if name.lower()=='style':errors.append('Inline style detected')
        if tag=='script':
            self.scripts.append(a)
            if not (a.get('src')=='assets/app-shell.js' or (a.get('type')=='application/ld+json' and not a.get('src'))):errors.append('Unexpected script tag')
        if tag in ('form','iframe','object','embed','base'):
            errors.append('Forbidden HTML element '+tag)
        if tag=='style':errors.append('Inline style not permitted')
        if tag=='template':self.templates.append(a.get('id'))
        if tag=='meta' and 'http-equiv' in a:self.meta[a['http-equiv'].lower()]=a.get('content','')
        if tag=='link':self.css.append(a)
        if tag=='img':self.images.append(a)
        if tag=='main':self.main+=1
        if tag=='h1':self.h1+=1
        if tag=='button':self.buttons.append(a)
        if tag=='a':
            href=a.get('href','')
            self.links.append(a)
            if href.startswith('#'):pass
            elif href.startswith('tel:'):
                if href!='tel:+79124665090':errors.append('Unexpected telephone destination')
            elif href.startswith('mailto:'):
                if not href.startswith('mailto:kodakprint@yandex.ru'):errors.append('Unexpected email destination')
                if '\n' in href or '\r' in href:errors.append('Unsafe email link')
            else:
                u=urlsplit(href)
                if u.scheme!='https' or u.hostname not in allowed_hosts or u.username or u.password:errors.append('Unapproved URL host / scheme')
            if a.get('target')=='_blank' and not all(x in a.get('rel','').split() for x in ('noopener','noreferrer')):
                errors.append('Unsafe new tab link')
a=Auditor();a.feed(html)
if a.main!=1 or a.h1!=1:errors.append('Main/heading hierarchy mismatch')
if html.count('data-action="photos"')<1 or html.count('data-action="id450"')<1:errors.append('First-screen services missing')
if len([x for x in a.buttons if 'app-tile' in x.get('class','').split()])!=6:errors.append('Expected exactly 6 smartphone tiles')
if len([x for x in a.buttons if 'dock-btn' in x.get('class','').split()])!=4:errors.append('Expected exactly 4 dock navigation buttons')
for name in ('photos','id450','documents','studio','shop','personal','bots','location','prices','help'):
    if 'screen-'+name not in a.templates:errors.append('Service screen missing: '+name)
for key,url in required_links.items():
    links=[x['href'] for x in a.links if x.get('id')==key]
    if not links or any(h!=url for h in links):errors.append('Critical link mismatch: '+key)
# Check the HTML also preserves service discovery routes in its nonexecutable templates.
for s in ('Фото на документы','450 ₽','35 ₽','55 ₽','750 ₽','850 ₽','35×45','8 шт.','3×4','6 шт.','4×6','4 шт.','любом фоне','Белый фон','Ровные плечи','В разработке','Не показываем неподтверждённые'):
    if s not in html:errors.append('Expected service text missing: '+s)
if 'id="store-photo-map"' not in html or 'assets/FotoMag_FACADE_APPROVED_web.webp' not in html:errors.append('Store location photo missing')
# Guard against burying the primary bot action under all app tiles.
idx_bot=html.find('id="bot-primary-cta"')
idx_grid=html.find('class="app-grid"')
if idx_bot < 0 or idx_grid < 0 or idx_bot>idx_grid:errors.append('Primary bot ordering action must be before app tiles')
if html.count('class="quick-bot"')!=3:errors.append('Direct bot choices under primary action missing')
if len(re.findall(r'data-format="(?:35x45|3x4|4x6)"',html))!=3:errors.append('Three photo formats selector missing')
if 'id="id-format-summary"' not in html or 'id="copy-order450"' not in html:errors.append('Dynamic format summary and copy control missing')
if 'id="id450-personal"' not in html:errors.append('Personal order action missing in photo service')
if html.count('id="order450-vk"') or html.count('id="order450-max"'):errors.append('Duplicate personal links in photo order: use personal screen only')
if 'portrait-demo' not in html or 'ФОТОСТУДИЙНАЯ ПОДГОТОВКА' not in html:errors.append('Studio processing promo missing')
if 'formatOptions' not in js or 'updateFormatUI' not in js:errors.append('Photo size selection not wired')
if 'fetch(' in js or 'XMLHttpRequest' in js or 'localStorage' in js:errors.append('Unexpected data upload or persistent storage')

if any('alt' not in img for img in a.images):errors.append('Image alt text missing')
if html.count('<meta http-equiv="Content-Security-Policy"')>1:errors.append('Duplicated CSP policy')
csp=a.meta.get('content-security-policy','')
for keyword in ("default-src 'none'","script-src 'self'","style-src 'self'","object-src 'none'","form-action 'none'","connect-src 'none'","base-uri 'none'"):
    if keyword not in csp:errors.append('CSP is too broad: '+keyword)
if 'unsafe-inline' in csp or 'unsafe-eval' in csp:errors.append('Unsafe CSP keyword')
if not any(x.get('href')=='assets/app-shell.css' and x.get('rel')=='stylesheet' for x in a.css):errors.append('Self-hosted stylesheet missing')
if not any(x.get('href')=='site.webmanifest' for x in a.css):errors.append('PWA manifest missing')
if not any(x.get('href')=='assets/fotomag_logo_official.svg' and x.get('rel')=='icon' for x in a.css):errors.append('Official favicon missing')
if len(a.scripts)!=2:errors.append('Unexpected script count')
if 'innerHTML' in js or 'eval(' in js or 'new Function(' in js or 'document.write(' in js:errors.append('Unsafe dynamic executable HTML')
if any(x in js for x in ('XMLHttpRequest','localStorage','sessionStorage','fetch(')):errors.append('Unexpected data transfer/storage capability')
if '.app-tile.pressed' not in css or '.dock-btn.pressed' not in css or '.quick-bot.pressed' not in css:errors.append('Smartphone press animation missing')
if 'history.pushState' not in js or "'#direct':'personal'" not in js:errors.append('Old deep-link compatibility missing')
if '&amp;amp;' in html:errors.append('Double encoded email link')
manifest=json.loads((ROOT/'site.webmanifest').read_text(encoding='utf-8'))
if manifest.get('start_url')!='./' or manifest.get('scope')!='./':errors.append('Manifest scope unexpected')
for f in [HTML,CSS,JS]:
    t=f.read_text(encoding='utf-8')
    if re.search(r'ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{80,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA )?PRIVATE KEY-----',t):errors.append('Possible secret in '+f.name)
if errors:
    print('BLOCKED FotoMag Smartphone release:\n'+'\n'.join(' - '+e for e in errors))
    sys.exit(1)
print('PASS FotoMag Smartphone: service tiles, routes, approved links, accessible contacts, CSP, no client uploads, SEO and assets.')
