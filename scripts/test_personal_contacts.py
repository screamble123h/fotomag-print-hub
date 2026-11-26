"""Exercise the two personal-contact entry paths in Chrome, locally or on Pages."""
import argparse
from contextlib import contextmanager, nullcontext
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from shutil import which
from threading import Thread
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FORMATS = (("35x45", "35×45 мм", 8), ("3x4", "3×4 см", 6), ("4x6", "4×6 см", 4))
GENERAL_NOTE = "Выберите способ связи и прикрепите фотографию или документ в открывшемся приложении."


@contextmanager
def local_site():
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        worker = Thread(target=server.serve_forever)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/"
        finally:
            server.shutdown()
            worker.join()


def email_fields(page):
    link = urlsplit(page.locator("#direct-email").get_attribute("href"))
    assert (link.scheme, link.path) == ("mailto", "kodakprint@yandex.ru"), link
    return parse_qs(link.query, keep_blank_values=True)


def check_general(page):
    expect(page.locator("#personal-service-context")).to_have_text(GENERAL_NOTE)
    fields = email_fields(page)
    assert fields == {"subject": ["FotoMag — личное сообщение"]}, fields


def select_format(page, key):
    button = page.locator(f'[data-format="{key}"]')
    button.click()
    expect(button).to_have_attribute("aria-pressed", "true")


def check_service_entries(page):
    for key, label, count in FORMATS:
        page.locator("#quick-id-photo").click()
        # Choose a different format first to catch payloads frozen on the first click.
        select_format(page, "3x4" if key == "4x6" else "4x6")
        select_format(page, key)
        caption = f"Фото на документы {label}, {count} шт. — 450 ₽"
        page.locator("#copy-order450").click()
        expect(page.locator("#copy-order450")).to_have_text("Скопировано ✓")
        assert page.evaluate("navigator.clipboard.readText()") == caption, label
        page.locator("#id450-personal").click()
        note = page.locator("#personal-service-context")
        expect(note).to_contain_text("Фото на документы за 450 ₽")
        expect(note).to_contain_text(f"{label} — {count} шт. на 10×15")
        fields = email_fields(page)
        assert fields["subject"] == ["FotoMag — фото на документы 450 ₽"], fields
        body, = fields["body"]
        assert f"Формат {label}, {count} шт. на листе 10×15 см." in body, body
        assert "Услуга 450 ₽." in body, body
        page.locator("#sheet-close").click()
        expect(page.locator("#sheet")).not_to_be_visible()


def check_general_entries(page, url):
    for leave, entry in (("close", "#quick-personal"), ("back", ".dock-btn[data-action=personal]")):
        page.locator("#quick-id-photo").click()
        select_format(page, "4x6")
        if leave == "close":
            page.locator("#sheet-close").click()
        else:
            page.go_back()
        expect(page.locator("#sheet")).not_to_be_visible()
        page.locator(entry).click()
        check_general(page)
        page.locator("#sheet-close").click()
        expect(page.locator("#sheet")).not_to_be_visible()
    for route in ("#personal-contacts", "#direct"):
        page.locator("#quick-id-photo").click()
        select_format(page, "4x6")
        page.goto(url + route)
        check_general(page)
        page.locator("#sheet-close").click()
        expect(page.locator("#sheet")).not_to_be_visible()



def check_upload_ui(page, url):
    """No phantom success; upload handler loads only after customer opens screen."""
    assert page.evaluate("Boolean(window.FotoMagDirectUpload)") is False
    page.locator("#direct-upload-primary").click()
    expect(page.locator("#sheet-title")).to_have_text("Отправить файлы")
    expect(page.locator("#upload-submit")).to_be_disabled()
    # Two legitimate deployment states: an unconfigured site or a configured
    # private AGFA HTTPS endpoint not reachable by this public CI runner.
    # Never treat either as successful upload admission.
    note = page.locator("#upload-availability").inner_text()
    assert any(part in note for part in
        ("готовится к запуску", "Прямая отправка работает при подключении", "Проверяем защищённое соединение", "Нет связи с приёмником", "Приём пока закрыт")), note
    assert page.evaluate("Boolean(window.FotoMagDirectUpload)") is True
    expect(page.locator("#upload-files")).to_have_attribute("multiple", "")
    expect(page.locator(".upload-heading")).to_have_text("Отправить файлы на печать")
    expect(page.locator(".upload-service-choice")).to_have_count(3)
    expect(page.locator('[data-upload-choice="photos"]')).to_have_attribute("aria-pressed", "true")
    page.locator('[data-upload-choice="documents"]').click()
    expect(page.locator("#upload-kind")).to_have_value("documents")
    expect(page.locator('[data-upload-choice="documents"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator('[data-upload-choice="photos"]')).to_have_attribute("aria-pressed", "false")
    page.locator('[data-upload-choice="id450"]').click()
    expect(page.locator("#upload-kind")).to_have_value("id450")
    # No rendered HTML from file names; no upload is attempted.
    test_file = "client_<img onerror=alert(1)>.pdf"
    page.locator("#upload-files").set_input_files({
        "name": test_file, "mimeType": "application/pdf", "buffer": b"%PDF-1.4\n%%EOF\n"
    })
    expect(page.locator("#upload-file-list li")).to_have_count(1)
    expect(page.locator(".upload-file-name")).to_have_text(test_file)
    expect(page.locator("#upload-file-list img")).to_have_count(0)
    expect(page.locator("#upload-submit")).to_be_disabled()
    page.locator("#sheet-close").click()
    for tile, kind, selector in (
        ("#quick-print-photo", "photos", ".upload-service-cta"),
        ("#quick-documents", "documents", ".upload-service-cta"),
        ("#quick-id-photo", "id450", "#id450-upload"),
    ):
        page.locator(tile).click()
        if kind == "id450":
            select_format(page, "35x45")
        page.locator(selector).click()
        expect(page.locator("#upload-kind")).to_have_value(kind)
        if kind == "id450":
            expect(page.locator("#upload-comment")).to_have_value("Фото на документы 35×45 мм, 8 шт. — 450 ₽")
        page.locator("#sheet-close").click()
    page.goto(url + "#send-files")
    expect(page.locator("#upload-submit")).to_be_disabled()
    page.locator("#sheet-close").click()
    expect(page.locator("#sheet")).not_to_be_visible()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", help="Published site root (defaults to a local server)")
    args = parser.parse_args()
    with (nullcontext(args.url) if args.url else local_site()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=which("google-chrome") or which("chromium"))
        for width, height in ((393, 852), (1280, 800)):
            context = browser.new_context(viewport={"width": width, "height": height},
                                          permissions=["clipboard-read", "clipboard-write"])
            page = context.new_page()
            page.goto(url)
            check_service_entries(page)
            print(f"PASS {width}px: three service formats, clipboard, hint and email", flush=True)
            check_general_entries(page, url)
            print(f"PASS {width}px: neutral home, dock and deep links after close or Back", flush=True)
            check_upload_ui(page, url)
            print(f"PASS {width}px: approved Design A chips, safe file preview, disabled upload and deep link", flush=True)
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
