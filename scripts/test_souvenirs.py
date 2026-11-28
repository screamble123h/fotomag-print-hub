"""Customer tests: FotoMag Wi-Fi shortcut, home order and souvenir request flow."""
import re
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from shutil import which
from urllib.parse import parse_qs,urlsplit
from playwright.sync_api import expect,sync_playwright
ROOT=Path(__file__).resolve().parents[1]
@contextmanager
def local_site():
    handler=partial(SimpleHTTPRequestHandler,directory=str(ROOT))
    with ThreadingHTTPServer(("127.0.0.1",0),handler) as server:
        worker=Thread(target=server.serve_forever)
        worker.start()
        try:yield f"http://127.0.0.1:{server.server_port}/"
        finally:server.shutdown();worker.join()
def main():
    with local_site() as url,sync_playwright() as p:
        browser=p.chromium.launch(executable_path=which("google-chrome") or which("chromium"))
        for width in (320,360,390,430,768,1366):
            context=browser.new_context(viewport={"width":width,"height":850},permissions=["clipboard-read","clipboard-write"])
            page=context.new_page()
            page.goto(url)
            expect(page.locator("h1")).to_have_text("Чем можем помочь?")
            assert page.locator("#bot-primary-cta").count()==1
            assert page.locator("#quick-personal").count()==1
            assert page.locator("#quick-souvenirs").count()==1
            assert page.locator("#bot-primary-cta").evaluate("(el)=>el.compareDocumentPosition(document.querySelector('#quick-souvenirs')) & Node.DOCUMENT_POSITION_FOLLOWING")!=0
            assert page.locator("#quick-personal").evaluate("(el)=>el.compareDocumentPosition(document.querySelector('#quick-souvenirs')) & Node.DOCUMENT_POSITION_FOLLOWING")!=0
            expect(page.locator("a.fm-call")).to_have_attribute("href","tel:+79124665090")
            assert page.locator("header .fm-wifi").is_visible()
            expect(page.locator(".social-contact__button--mail")).to_contain_text("Почта")
            page.locator("header .fm-wifi").click()
            expect(page.locator("#sheet-title")).to_have_text("Бесплатный Wi‑Fi")
            expect(page.locator(".wifi-creds")).to_contain_text("AGFA")
            expect(page.locator(".wifi-qr")).to_have_attribute("src","assets/wifi-agfa.svg")
            expect(page.locator("#wifi-connect")).to_have_text("Подключиться")
            page.locator("#wifi-connect").click()
            expect(page.locator("#wifi-connect-help")).to_be_visible()
            expect(page.locator("#wifi-connect-help")).to_contain_text("Пароль скопирован.")
            expect(page.locator("#wifi-connect-help")).to_contain_text("Откройте настройки Wi-Fi этого телефона")
            assert page.evaluate("() => navigator.clipboard.readText()") == "00001111"
            page.locator("#sheet-close").click()
            page.locator("#quick-souvenirs").click()
            expect(page).to_have_url(re.compile(r"/souvenirs.html$"))
            expect(page.locator('input[name="gift"]')).to_have_count(28)
            expect(page.locator("h1")).to_have_text("Фотосувениры")
            for group in page.locator("details.gift-group").all():
                expect(group).not_to_have_attribute("open", "")
            page.locator("#gift-group-1 summary").click()
            page.locator("#gift-group-3 summary").click()
            page.locator('input[value="Футболки с фото"]').check()
            page.locator('input[value="Фотокристаллы"]').check()
            expect(page.locator("#gift-chosen")).to_contain_text("Выбрано: 2")
            expect(page.locator("#gift-request-text")).to_have_value(re.compile("Футболки с фото"))
            mail=page.locator("#gift-email").get_attribute("href")
            assert urlsplit(mail).scheme=="mailto"
            assert "Фотокристаллы" in parse_qs(urlsplit(mail).query)["body"][0]
            page.locator("#gift-copy").click()
            expect(page.locator("#gift-feedback")).to_contain_text("скопирован")
            copied=page.evaluate("navigator.clipboard.readText()")
            assert "Футболки с фото" in copied and "Фотокристаллы" in copied
            print(f"PASS FotoMag V6 at {width}px: contact order, Wi-Fi instructions, souvenir catalog and enquiry",flush=True)
            context.close()
        browser.close()
if __name__=="__main__":main()
