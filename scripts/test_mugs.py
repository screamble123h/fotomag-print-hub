# -*- coding: utf-8 -*-
"""Playwright smoke tests for the full FotoMag mug ordering journey."""
import re
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import quote
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
@contextmanager
def site():
 handler=partial(SimpleHTTPRequestHandler,directory=str(ROOT))
 with ThreadingHTTPServer(("127.0.0.1",0),handler) as srv:
  th=Thread(target=srv.serve_forever);th.start()
  try:yield f"http://127.0.0.1:{srv.server_port}/"
  finally:srv.shutdown();th.join()
def main():
 with site() as url,sync_playwright() as p:
  browser=p.chromium.launch(executable_path=__import__('shutil').which('google-chrome') or __import__('shutil').which('chromium'))
  for width in (360,390,430,768,1366):
   context=browser.new_context(viewport={"width":width,"height":860},permissions=["clipboard-read","clipboard-write"])
   page=context.new_page()
   page.goto(url+"mugs.html")
   expect(page.locator(".tile")).to_have_count(8)
   expect(page.locator("#stepLabel")).to_have_text("ШАГ 1 ИЗ 4")
   expect(page.locator("button[data-series]")).to_have_count(8)
   page.locator("button[data-series]").first.click()
   expect(page.locator("#stepLabel")).to_have_text("ШАГ 2 ИЗ 4")
   assert page.locator("button[data-item]").count()>=1
   page.locator("button[data-item]").first.click()
   expect(page.locator("#stepLabel")).to_have_text("ШАГ 3 ИЗ 4")
   page.locator("#forwardBtn").click()
   expect(page.locator("#stepLabel")).to_have_text("ШАГ 4 ИЗ 4")
   expect(page.locator("button[data-mode='direct']")).to_have_class(re.compile("active"))
   page.locator("button[data-channel='mail']").click()
   expect(page.locator("#forwardBtn")).to_be_enabled()
   expect(page.locator("#requestText")).to_contain_text("650 ₽")
   expect(page.locator("#requestText")).to_have_value(re.compile(r"Ссылка на товар: .*mugs\.html\?sku=classic"))
   page.locator("#quantity").fill("3")
   page.locator("#comment").fill("Подарок, фото с двух сторон")
   expect(page.locator("#requestText")).to_have_value(re.compile("Количество: 3 шт."))
   assert "Подарок" not in page.url and "comment" not in page.url
   page.reload()
   expect(page.locator("#quantity")).to_have_value("3")
   expect(page.locator("#comment")).to_have_value("Подарок, фото с двух сторон")
   page.locator("button[data-copy]").click()
   expect(page.locator("#sendStatus")).to_contain_text("скопирован")
   page.locator("#backBtn").click();expect(page.locator("#stepLabel")).to_have_text("ШАГ 3 ИЗ 4")
   page.locator("#forwardBtn").click()
   expect(page.locator("#quantity")).to_have_value("3")
   expect(page.locator("#comment")).to_have_value("Подарок, фото с двух сторон")
   page.locator("#backBtn").click();expect(page.locator("#stepLabel")).to_have_text("ШАГ 3 ИЗ 4")
   page.locator("#backBtn").click();expect(page.locator("#stepLabel")).to_have_text("ШАГ 2 ИЗ 4")
   page.locator("#backBtn").click()
   page.locator("#searchInput").fill("Stackable")
   page.locator('button[data-series="Stackable"]').click()
   expect(page.locator('button[data-item="21371"]')).to_have_count(1)
   page.locator('button[data-zoom="21371"]').click()
   expect(page.locator("#photoDialog")).to_be_visible()
   expect(page.locator("#photoImage")).to_have_attribute("src",re.compile(r"21371.webp"))
   page.go_back()
   expect(page.locator("#photoDialog")).not_to_be_visible()
   expect(page.locator('button[data-zoom="21371"]')).to_be_focused()
   page.locator('button[data-item="21371"]').click()
   expect(page.locator("#stepLabel")).to_have_text("ШАГ 3 ИЗ 4")
   expect(page.locator(".detail-panel")).to_contain_text("21371")
   assert "sku=21371" in page.url
   page.go_back()
   expect(page.locator("#stepLabel")).to_have_text("ШАГ 2 ИЗ 4")
   page.go_forward()
   expect(page.locator(".detail-panel")).to_contain_text("21371")
   assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
   page.goto(url+"mugs.html?group="+quote("Хамелеоны"))
   expect(page.locator('button[data-filter="Хамелеоны"]')).to_have_attribute("aria-pressed","true")
   expect(page.locator("#forwardBtn")).to_be_disabled()
   page.goto(url+"mugs.html?group="+quote("Термокружки"))
   expect(page.locator(".tile")).to_have_count(0)
   expect(page.locator(".empty-state")).to_contain_text("пока нет подтверждённых моделей")
   expect(page.locator('button[data-filter="Термокружки"]')).to_have_attribute("aria-pressed","true")
   expect(page.locator("#forwardBtn")).to_be_disabled()
   page.goto(url+"mugs.html?sku=10335")
   expect(page.locator("#stepLabel")).to_have_text("ШАГ 3 ИЗ 4")
   expect(page.locator(".detail-panel")).to_contain_text("1\u00a0250 ₽")
   page.locator("#forwardBtn").click()
   expect(page.locator("#requestText")).to_have_value(re.compile("Артикул: 10335"))
   page.locator("#quantity").fill("1.5")
   page.locator("#comment").click()
   expect(page.locator("#quantity")).to_have_value("1")
   expect(page.locator("#requestText")).to_have_value(re.compile("Количество: 1 шт."))
   assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
   page.goto(url+"souvenirs.html")
   expect(page.locator("a.gift-mug-top")).to_have_attribute("href","mugs.html")
   assert page.locator("a.gift-mug-link").count()==5
   print(f"PASS mugs {width}px: request fields, stable SKU links, reload/back/forward, photo focus, truthful empty group, integer quantity and souvenir routes",flush=True)
   context.close()
  browser.close()
if __name__=="__main__":main()
