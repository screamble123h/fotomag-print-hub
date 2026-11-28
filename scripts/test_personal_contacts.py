"""Exercise personal orders, history and unsent upload drafts in Chrome CI.

No messages, uploads or external popups are sent. Public-origin navigation uses
checked-out files as fixtures, without contacting the store's receiver.
"""
import argparse
from contextlib import contextmanager, nullcontext
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from mimetypes import guess_type
from pathlib import Path
from shutil import which
from threading import Thread
from urllib.parse import parse_qs, unquote, urlsplit

from playwright.sync_api import expect, sync_playwright
from test_responsive import WIDTHS, assert_sheet_layout, check_home_layout, check_keyboard_dialog, check_text_enlargement

ROOT = Path(__file__).resolve().parents[1]
FORMATS = (("35x45", "35×45 мм", 8), ("3x4", "3×4 см", 6), ("4x6", "4×6 см", 4))
GENERAL_NOTE = "Выберите способ связи и прикрепите фотографию или документ в открывшемся приложении."
PUBLIC_URL = "https://screamble123h.github.io/fotomag-print-hub/"
LOCAL_FORM = "https://fotomag-izhevsk.dynv6.net:8443/#send-files"
CAPTURE_POPUPS = """(() => {
  window.__opened = [];
  window.open = (url, target, features) => {
    window.__opened.push({url: String(url), target, features});
    return null;
  };
})();"""


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


def close_sheet(page):
    page.locator("#sheet-close").click()
    expect(page.locator("#sheet")).not_to_be_visible()


def select_format(page, key):
    button = page.locator(f'[data-format="{key}"]')
    button.click()
    expect(button).to_have_attribute("aria-pressed", "true")


def check_general(page):
    expect(page.locator("#personal-service-context")).to_have_text(GENERAL_NOTE)
    assert email_fields(page) == {"subject": ["FotoMag — личное сообщение"]}
    expect(page.locator("#personal-order-text")).to_be_hidden()
    expect(page.locator("#personal-order-text")).to_have_value("")
    expect(page.locator("#copy-personal-order")).to_be_hidden()


def check_service_context(page, label, count, copy=True):
    note = page.locator("#personal-service-context")
    expect(note).to_contain_text("Фото на документы за 450 ₽")
    expect(note).to_contain_text(f"{label} — {count} шт. на 10×15")
    fields = email_fields(page)
    assert fields["subject"] == ["FotoMag — фото на документы 450 ₽"], fields
    body, = fields["body"]
    assert f"Формат {label}, {count} шт. на листе 10×15 см." in body, body
    assert "Услуга 450 ₽." in body and "Фото прикрепляю." in body, body
    expect(page.locator("#personal-order-text")).to_have_value(body)
    expect(page.locator("#personal-order-text")).to_have_attribute("readonly", "")
    if copy:
        page.locator("#copy-personal-order").click()
        expect(page.locator("#copy-personal-order")).to_have_text("Скопировано ✓")
        assert page.evaluate("navigator.clipboard.readText()") == body
    assert_sheet_layout(page, "#copy-personal-order", "#direct-email", "#direct-tg")


def check_service_entries(page):
    for key, label, count in FORMATS:
        page.locator("#quick-id-photo").click()
        # Select a different option first to catch a payload frozen on first click.
        select_format(page, "3x4" if key == "4x6" else "4x6")
        select_format(page, key)
        caption = f"Фото на документы {label}, {count} шт. — 450 ₽"
        page.locator("#copy-order450").click()
        expect(page.locator("#copy-order450")).to_have_text("Скопировано ✓")
        assert page.evaluate("navigator.clipboard.readText()") == caption, label
        page.locator("#id450-personal").click()
        check_service_context(page, label, count)
        close_sheet(page)


def check_general_entries(page, url):
    for leave, entry in (("close", "#quick-personal"), ("back", ".dock-btn[data-action=personal]")):
        page.locator("#quick-id-photo").click()
        select_format(page, "4x6")
        if leave == "close":
            close_sheet(page)
        else:
            page.go_back()
        expect(page.locator("#sheet")).not_to_be_visible()
        page.locator(entry).click()
        check_general(page)
        close_sheet(page)
    for route in ("#personal-contacts", "#direct"):
        page.locator("#quick-id-photo").click()
        select_format(page, "4x6")
        page.goto(url + route)
        check_general(page)
        close_sheet(page)


def check_history(page, url):
    page.goto(url)
    page.locator("#quick-id-photo").click()
    select_format(page, "4x6")
    page.locator("#id450-personal").click()
    check_service_context(page, "4×6 см", 4, copy=False)
    page.go_back()
    expect(page.locator('[data-format="4x6"]')).to_have_attribute("aria-pressed", "true")
    # Forward must retain its own original order despite editing the previous entry.
    select_format(page, "3x4")
    page.go_forward()
    check_service_context(page, "4×6 см", 4, copy=False)
    page.go_back()
    expect(page.locator('[data-format="3x4"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#id-format-summary")).to_contain_text("3×4 см — 6 фото")
    page.go_forward()
    check_service_context(page, "4×6 см", 4, copy=False)
    route_before_close = page.url
    # Native close is queued. Reopen before it fires to reproduce the stale event.
    page.evaluate("""() => new Promise(resolve => {
      const dialog = document.getElementById('sheet');
      dialog.addEventListener('close', () => resolve(), {once: true});
      dialog.close();
      dialog.showModal();
    })""")
    assert page.url == route_before_close, "A stale close erased the reopened route"
    expect(page.locator("#sheet")).to_be_visible()
    check_service_context(page, "4×6 см", 4, copy=False)
    close_sheet(page)


def wait_for_upload(page):
    # The module fills this live status after onView. Locator polling works with
    # script-src 'self'; wait_for_function would require CSP-disallowed eval.
    expect(page.locator("#upload-availability")).not_to_be_empty(timeout=30000)
    assert page.evaluate("() => Boolean(window.FotoMagDirectUpload)"), "Upload handler did not initialize"


def check_reload_context(page, url):
    # The user's latest choice supersedes the format in the original entry URL.
    page.goto(url + "?format=35x45#order450")
    select_format(page, "4x6")
    page.reload()
    expect(page.locator('[data-format="4x6"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#id-format-summary")).to_contain_text("4×6 см — 4 фото")
    page.locator("#id450-personal").click()
    check_service_context(page, "4×6 см", 4, copy=False)
    page.reload()
    check_service_context(page, "4×6 см", 4, copy=False)
    assert page.evaluate("window.__opened.length") == 0
    # History may retain a context marker, but its arbitrary labels are not used.
    page.evaluate("""() => history.replaceState({...history.state,
      orderFormat: {label:'НЕВЕРНЫЙ ФОРМАТ', count:999}}, '', location.href)""")
    page.reload()
    check_service_context(page, "4×6 см", 4, copy=False)
    # An unrelated history entry cannot turn a plain contact link into an order.
    page.evaluate("""() => history.replaceState({...history.state, view:'id450'}, '', location.href)""")
    page.reload()
    check_general(page)
    page.goto(url + "?format=3x4#order450")
    expect(page.locator('[data-format="3x4"]')).to_have_attribute("aria-pressed", "true")
    page.goto(url + "?format=4x6#personal-contacts")
    check_general(page)
    page.reload()
    check_general(page)

    for tile, kind, selector in (
        ("#quick-print-photo", "photos", ".upload-service-cta"),
        ("#quick-documents", "documents", ".upload-service-cta"),
        ("#quick-id-photo", "id450", "#id450-upload"),
    ):
        if page.goto(url) is None:
            page.reload()
        page.locator(tile).click()
        if kind == "id450":
            select_format(page, "4x6")
        page.locator(selector).click()
        wait_for_upload(page)
        page.reload()
        wait_for_upload(page)
        expect(page.locator("#upload-kind")).to_have_value(kind)
        if kind == "id450":
            expect(page.locator("#upload-format")).to_have_value("4x6")
            expect(page.locator("#upload-comment")).to_have_value("Фото на документы 4×6 см, 4 шт. — 450 ₽")
        assert page.evaluate("window.__opened.length") == 0, "Reload opened an unrequested receiver tab"

    page.goto(url + "?kind=documents&format=35x45#send-files")
    wait_for_upload(page)
    page.locator('[data-upload-choice="id450"]').click()
    expect(page.locator("#upload-format-field")).to_be_visible()
    page.locator("#upload-format").select_option("3x4")
    page.reload()
    wait_for_upload(page)
    expect(page.locator("#upload-kind")).to_have_value("id450")
    expect(page.locator("#upload-format")).to_have_value("3x4")
    expect(page.locator("#upload-comment")).to_have_value("Фото на документы 3×4 см, 6 шт. — 450 ₽")
    assert page.evaluate("window.__opened.length") == 0


def check_upload_ui(page, url):
    """Retain the disabled-upload, lazy loading and filename safety gate."""
    page.goto(url)
    assert page.evaluate("Boolean(window.FotoMagDirectUpload)") is False
    page.locator("#direct-upload-primary").click()
    expect(page.locator("#sheet-title")).to_have_text("Отправить файлы")
    wait_for_upload(page)
    expect(page.locator("#upload-submit")).to_be_disabled()
    note = page.locator("#upload-availability").inner_text()
    assert any(part in note for part in
               ("готовится к запуску", "Прямая отправка работает при подключении", "Проверяем защищённое соединение", "Нет связи с приёмником", "Приём пока закрыт")), note
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
    test_file = "client_<img onerror=alert(1)>.pdf"
    page.locator("#upload-files").set_input_files({
        "name": test_file, "mimeType": "application/pdf", "buffer": b"%PDF-1.4\n%%EOF\n"
    })
    expect(page.locator("#upload-file-list li")).to_have_count(1)
    expect(page.locator(".upload-file-name")).to_have_text(test_file)
    expect(page.locator("#upload-file-list img")).to_have_count(0)
    expect(page.locator("#upload-submit")).to_be_disabled()
    # Discard explicitly: changing the service must not silently erase a draft.
    page.locator("#upload-new").click()
    expect(page.locator("#upload-file-list li")).to_have_count(0)
    close_sheet(page)
    for tile, kind, selector in (
        ("#quick-print-photo", "photos", ".upload-service-cta"),
        ("#quick-documents", "documents", ".upload-service-cta"),
        ("#quick-id-photo", "id450", "#id450-upload"),
    ):
        page.locator(tile).click()
        if kind == "id450":
            select_format(page, "35x45")
        page.locator(selector).click()
        wait_for_upload(page)
        expect(page.locator("#upload-kind")).to_have_value(kind)
        if kind == "id450":
            expect(page.locator("#upload-format")).to_have_value("35x45")
            expect(page.locator("#upload-comment")).to_have_value("Фото на документы 35×45 мм, 8 шт. — 450 ₽")
        close_sheet(page)
    page.goto(url + "#send-files")
    wait_for_upload(page)
    expect(page.locator("#upload-submit")).to_be_disabled()
    close_sheet(page)


def check_draft_lifetime(page, url):
    page.goto(url)
    page.locator("#direct-upload-primary").click()
    wait_for_upload(page)
    page.locator('[data-upload-choice="documents"]').click()
    filename = "Проверка черновика.pdf"
    page.locator("#upload-files").set_input_files({
        "name": filename, "mimeType": "application/pdf", "buffer": b"%PDF-1.4\n%%EOF\n"
    })
    page.locator("#upload-name").fill("Тестовый клиент")
    page.locator("#upload-comment").fill("Тест: две копии, цветная печать")
    page.locator(".upload-contact-extra summary").click()
    page.locator("#upload-phone").fill("+7 000 000-00-00")
    page.locator("#upload-consent").check()
    assert page.evaluate("window.FotoMagDirectUpload.getState().hasDraft") is True
    close_sheet(page)
    page.locator("#quick-id-photo").click()
    select_format(page, "4x6")
    page.locator("#id450-upload").click()
    wait_for_upload(page)
    expect(page.locator("#upload-kind")).to_have_value("documents")
    expect(page.locator("#upload-name")).to_have_value("Тестовый клиент")
    expect(page.locator("#upload-comment")).to_have_value("Тест: две копии, цветная печать")
    expect(page.locator("#upload-phone")).to_have_value("+7 000 000-00-00")
    expect(page.locator("#upload-consent")).to_be_checked()
    expect(page.locator(".upload-file-name")).to_have_text(filename)
    assert page.locator("#upload-files").evaluate("el => [...el.files].map(f => f.name)") == [filename]
    expect(page.locator("#upload-submit")).to_be_disabled()
    expect(page.locator("#upload-status")).not_to_contain_text("принята сервером")
    expect(page.locator("#upload-status")).not_to_contain_text("доставлена на компьютер")
    page.locator("#upload-new").click()
    expect(page.locator("#upload-file-list li")).to_have_count(0)
    assert page.locator("#upload-files").evaluate("el => el.files.length") == 0
    for field in ("name", "comment", "phone"):
        expect(page.locator("#upload-" + field)).to_have_value("")
    expect(page.locator("#upload-consent")).not_to_be_checked()
    expect(page.locator("#upload-new")).to_be_hidden()
    state = page.evaluate("window.FotoMagDirectUpload.getState()")
    assert not state["hasDraft"] and not state["pending"] and not state["received"] and not state["receipt"], state
    close_sheet(page)
    page.locator("#quick-id-photo").click()
    select_format(page, "4x6")
    page.locator("#id450-upload").click()
    wait_for_upload(page)
    expect(page.locator("#upload-kind")).to_have_value("id450")
    expect(page.locator("#upload-format")).to_have_value("4x6")
    expect(page.locator("#upload-comment")).to_have_value("Фото на документы 4×6 см, 4 шт. — 450 ₽")
    close_sheet(page)


def assert_local_destination(call, kind, format_key=None):
    url = urlsplit(call["url"])
    assert (url.scheme, url.netloc, url.path, url.fragment) == (
        "https", "fotomag-izhevsk.dynv6.net:8443", "/", "send-files"), call
    fields = parse_qs(url.query)
    assert fields.get("kind") == [kind], call
    if format_key is not None:
        assert fields.get("format") == [format_key], call
    assert set(fields) <= {"kind", "format"}, call
    assert call["target"] == "_blank" and set(call["features"].split(",")) == {"noopener", "noreferrer"}, call


def check_incoming_handoff(page, url):
    for key, label, count in FORMATS:
        page.goto(url + f"?kind=id450&format={key}#send-files")
        wait_for_upload(page)
        expect(page.locator("#upload-kind")).to_have_value("id450")
        expect(page.locator("#upload-format")).to_have_value(key)
        expect(page.locator("#upload-comment")).to_have_value(f"Фото на документы {label}, {count} шт. — 450 ₽")
        assert page.evaluate("window.__opened.length") == 0
    # Object prototype names are not supported formats.
    for invalid_format in ("constructor", "__proto__"):
        page.goto(url + f"?kind=id450&format={invalid_format}#send-files")
        wait_for_upload(page)
        expect(page.locator("#upload-kind")).to_have_value("id450")
        expect(page.locator("#upload-format")).to_have_value("35x45")
        expect(page.locator("#upload-comment")).to_have_value("Фото на документы 35×45 мм, 8 шт. — 450 ₽")
    page.goto(url + "?kind=untrusted&format=unknown#send-files")
    wait_for_upload(page)
    expect(page.locator("#upload-kind")).to_have_value("photos")
    expect(page.locator("#upload-format")).to_have_value("35x45")
    expect(page.locator("#upload-comment")).to_have_value("")
    assert page.evaluate("window.__opened.length") == 0


def check_fallback_destination(page, url):
    page.goto(url)
    page.locator("#quick-id-photo").click()
    select_format(page, "3x4")
    page.locator("#id450-upload").click()
    wait_for_upload(page)
    page.locator("#upload-name").fill("Частное имя")
    page.locator("#upload-comment").fill("Частный комментарий")
    # Ignore a production-host automatic handoff if targeting published Pages.
    page.evaluate("window.__opened = []")
    button = page.locator("#upload-recheck")
    button.click()
    calls = page.evaluate("window.__opened")
    assert len(calls) == 1, calls
    assert_local_destination(calls[0], "id450", "3x4")
    expect(page.locator("#upload-status")).to_contain_text("в этой вкладке они не отправлены")
    invalid = (
        "javascript:alert(1)",
        "http://fotomag-izhevsk.dynv6.net:8443/#send-files",
        "https://fotomag-izhevsk.dynv6.net.evil.invalid:8443/#send-files",
        "https://user@fotomag-izhevsk.dynv6.net:8443/#send-files",
        "https://fotomag-izhevsk.dynv6.net:443/#send-files",
        "https://fotomag-izhevsk.dynv6.net:8443/admin#send-files",
        "https://fotomag-izhevsk.dynv6.net:8443/?next=elsewhere#send-files",
        "https://fotomag-izhevsk.dynv6.net:8443/#other",
    )
    for destination in invalid:
        button.evaluate("(el, value) => el.dataset.formUrl = value", destination)
        button.click()
        assert page.evaluate("window.__opened.length") == 1, destination
        expect(page.locator("#upload-status")).to_contain_text("Не удалось открыть форму FotoMag")
    button.evaluate("(el, value) => el.dataset.formUrl = value", LOCAL_FORM)
    close_sheet(page)


def public_fixture(route):
    """Serve only checked-out files; reject external traffic and write requests."""
    request = route.request
    if request.method != "GET" or not request.url.startswith(PUBLIC_URL):
        route.abort()
        return
    relative = unquote(urlsplit(request.url).path[len("/fotomag-print-hub/"):]) or "index.html"
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        route.fulfill(status=404, body="Not found")
        return
    route.fulfill(status=200, path=str(path), content_type=guess_type(path.name)[0] or "application/octet-stream")


def check_public_handoff(browser):
    context = browser.new_context(viewport={"width": 390, "height": 860})
    context.route("**/*", public_fixture)
    context.add_init_script(CAPTURE_POPUPS)
    page = context.new_page()
    for key, kind in ((None, "photos"), (None, "documents"), *((key, "id450") for key, _, _ in FORMATS)):
        response = page.goto(PUBLIC_URL)
        if response is None:
            # Removing #send-files may be same-document navigation. Each case
            # requires fresh popup capture and upload state, not the previous draft.
            page.reload()
        if kind == "photos":
            page.locator("#direct-upload-primary").click()
        else:
            page.locator("#quick-documents" if kind == "documents" else "#quick-id-photo").click()
            if key:
                select_format(page, key)
            page.locator(".upload-service-cta" if kind == "documents" else "#id450-upload").click()
        wait_for_upload(page)
        # The click and completed onView already precede this synchronous capture.
        assert page.evaluate("() => window.__opened.length") == 1
        assert_local_destination(page.evaluate("window.__opened[0]"), kind, key)
        expect(page.locator("#upload-kind")).to_have_value(kind)
        # Traversing history must not launch more tabs.
        page.go_back()
        page.go_forward()
        expect(page.locator("#sheet-title")).to_have_text("Отправить файлы")
        assert page.evaluate("window.__opened.length") == 1
        page.reload()
        wait_for_upload(page)
        expect(page.locator("#upload-kind")).to_have_value(kind)
        if key:
            expect(page.locator("#upload-format")).to_have_value(key)
        assert page.evaluate("window.__opened.length") == 0, "Reload opened an unrequested receiver tab"

    response = page.goto(PUBLIC_URL)
    if response is None:
        page.reload()
    page.locator("#direct-upload-primary").click()
    wait_for_upload(page)
    page.locator('[data-upload-choice="documents"]').click()
    page.locator("#upload-comment").fill("Сохранённый черновик документов")
    close_sheet(page)
    page.locator("#quick-id-photo").click()
    select_format(page, "4x6")
    page.locator("#id450-upload").click()
    wait_for_upload(page)
    expect(page.locator("#upload-kind")).to_have_value("documents")
    expect(page.locator("#upload-comment")).to_have_value("Сохранённый черновик документов")
    assert page.evaluate("window.__opened.length") == 1, "Restoring a draft opened a mismatching new form"
    page.locator("#upload-recheck").click()
    assert page.evaluate("window.__opened.length") == 2
    assert_local_destination(page.evaluate("window.__opened[1]"), "documents", "35x45")
    # Explicit reset allows a new service handoff with the newly selected format.
    page.locator("#upload-new").click()
    close_sheet(page)
    page.locator("#quick-id-photo").click()
    select_format(page, "4x6")
    page.locator("#id450-upload").click()
    wait_for_upload(page)
    assert page.evaluate("window.__opened.length") == 3
    assert_local_destination(page.evaluate("window.__opened[2]"), "id450", "4x6")
    context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", help="Published static root (defaults to a local server)")
    args = parser.parse_args()
    with (nullcontext(args.url) if args.url else local_site()) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=which("google-chrome") or which("chromium"))
        for width in WIDTHS:
            context = browser.new_context(viewport={"width": width, "height": 860},
                                          permissions=["clipboard-read", "clipboard-write"])
            context.add_init_script(CAPTURE_POPUPS)
            write_attempts = []
            def prohibit_writes(route):
                if route.request.method not in ("GET", "HEAD"):
                    write_attempts.append((route.request.method, route.request.url))
                    route.abort()
                else:
                    route.continue_()
            context.route("**/*", prohibit_writes)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            check_home_layout(page)
            check_keyboard_dialog(page)
            check_service_entries(page)
            check_general_entries(page, url)
            check_history(page, url)
            check_reload_context(page, url)
            print(f"PASS {width}px: three formats, prepared text/email/clipboard, neutral entry, keyboard and history", flush=True)
            check_upload_ui(page, url)
            check_draft_lifetime(page, url)
            check_fallback_destination(page, url)
            check_incoming_handoff(page, url)
            print(f"PASS {width}px: lazy disabled upload, safe filenames, retained draft, explicit reset and destination allowlist", flush=True)
            check_text_enlargement(page, url)
            assert not errors, f"Uncaught browser errors: {errors}"
            assert not write_attempts, f"Unrequested network writes: {write_attempts}"
            print(f"PASS {width}px: reachable controls, modal/dock hit-testing and 200% root-font reflow", flush=True)
            context.close()
        check_public_handoff(browser)
        print("PASS public hostname fixture: kind/format handoff, no PII in URL and no popup on Back/Forward", flush=True)
        browser.close()


if __name__ == "__main__":
    main()
