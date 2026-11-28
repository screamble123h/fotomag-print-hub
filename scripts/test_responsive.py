"""Browser-CI layout checks, including verified 200% root-font enlargement.

Root-font scaling tests text reflow, not physical phones or pinch zoom.
"""
from playwright.sync_api import expect

WIDTHS = (360, 390, 430, 768, 1366)


def assert_no_horizontal_overflow(page):
    failures = page.evaluate("""() => {
      const checks = [document.documentElement, document.querySelector('#screen-scroll'),
        document.querySelector('#sheet[open]'), document.querySelector('#sheet[open] #sheet-body')];
      return checks.filter(Boolean).filter(el => el.clientWidth && el.scrollWidth > el.clientWidth + 1)
        .map(el => ({element: el.id || el.tagName, client: el.clientWidth, scroll: el.scrollWidth}));
    }""")
    assert not failures, f"Horizontal content is clipped or scrolls: {failures}"


def assert_reachable(page, selector):
    """The complete control can be scrolled into view, clear of the dock/header."""
    control = page.locator(selector)
    expect(control).to_have_count(1)
    expect(control).to_be_visible()
    control.scroll_into_view_if_needed()
    geometry = control.evaluate("""el => {
      const box = el.getBoundingClientRect();
      const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
      return {left: box.left, right: box.right, top: box.top, bottom: box.bottom,
        width: box.width, height: box.height, viewportWidth: innerWidth, viewportHeight: innerHeight,
        hit: Boolean(hit && (hit === el || el.contains(hit))),
        coveredBy: hit ? (hit.id || hit.className || hit.tagName) : null};
    }""")
    assert geometry["width"] > 0 and geometry["height"] > 0, (selector, geometry)
    assert geometry["left"] >= -1 and geometry["right"] <= geometry["viewportWidth"] + 1, (selector, geometry)
    assert geometry["top"] >= -1 and geometry["bottom"] <= geometry["viewportHeight"] + 1, (selector, geometry)
    assert geometry["hit"], f"Control is covered: {selector}: {geometry}"


def assert_sheet_layout(page, *controls):
    expect(page.locator("#sheet")).to_be_visible()
    assert_no_horizontal_overflow(page)
    for selector in controls:
        assert_reachable(page, selector)
    assert_reachable(page, "#sheet-close")


def check_home_layout(page):
    assert_no_horizontal_overflow(page)
    for selector in (".fm-call", ".fm-wifi", "#quick-bot-vk", "#quick-bot-max", "#quick-bot-tg",
                     "#quick-personal", "#quick-id-photo", "#direct-upload-primary",
                     '.dock-btn[data-action="home"]', '.dock-btn[data-action="personal"]'):
        assert_reachable(page, selector)


def check_keyboard_dialog(page):
    trigger = page.locator("#quick-personal")
    trigger.focus()
    page.keyboard.press("Enter")
    expect(page.locator("#sheet")).to_be_visible()
    expect(page.locator("#sheet-close")).to_be_focused()
    for selector in ("#direct-vk", "#direct-max", "#direct-email", "#direct-tg"):
        page.keyboard.press("Tab")
        expect(page.locator(selector)).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(page.locator("#direct-email")).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.locator("#sheet")).not_to_be_visible()
    expect(trigger).to_be_focused()


def check_text_enlargement(page, url):
    page.goto(url)
    note = page.locator(".social-contact__note").first
    before = note.evaluate("el => parseFloat(getComputedStyle(el).fontSize)")
    page.evaluate("document.documentElement.style.fontSize = '200%'")
    after = note.evaluate("el => parseFloat(getComputedStyle(el).fontSize)")
    assert after >= before * 1.95, f"Text size did not enlarge: {before} -> {after}"
    check_home_layout(page)
    page.locator("#quick-id-photo").click()
    assert_sheet_layout(page, '[data-format="35x45"]', '[data-format="3x4"]',
                        '[data-format="4x6"]', "#id450-personal", "#id450-upload")
    page.locator("#id450-personal").click()
    assert_sheet_layout(page, "#copy-personal-order", "#direct-vk", "#direct-max", "#direct-email", "#direct-tg")
    page.locator("#sheet-close").click()
    page.locator("#direct-upload-primary").click()
    expect(page.locator("#upload-availability")).not_to_be_empty()
    assert_sheet_layout(page, '[data-upload-choice="photos"]', '[data-upload-choice="documents"]',
                        '[data-upload-choice="id450"]', '.upload-picker', '#upload-name',
                        '#upload-comment', '#upload-submit', '#upload-recheck')
    page.locator("#sheet-close").click()
    page.locator(".fm-wifi").click()
    assert_sheet_layout(page, "#wifi-connect")
    page.locator("#sheet-close").click()
