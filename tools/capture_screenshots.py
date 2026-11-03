"""Capture screenshots of the real application in headless Chrome.

    .venv\\Scripts\\python.exe tools\\capture_screenshots.py

Starts its own server on a fresh database with sample sales (about 55
percent of seats sold to sample accounts), then walks through the main
states. Writes PNG files to docs/screenshots/. Nothing is staged by
editing the page: every state is reached through the interface or the API.
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.support import live_server  # noqa: E402

OUT = ROOT / "docs" / "screenshots"


def sign_in(page, url, username="mei"):
    page.goto(url)
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill("demo-pass")
    page.get_by_role("button", name="Sign in").click()
    page.locator('[data-seat="A-01"]').wait_for()


def first_free(page, candidates):
    for seat_id in candidates:
        if page.locator(f'[data-seat="{seat_id}"]').get_attribute("data-state") == "available":
            return seat_id
    raise RuntimeError("no free seat among candidates")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    work = ROOT / ".local" / "screens"
    work.mkdir(parents=True, exist_ok=True)
    server = live_server.start(str(work / f"screens-{int(time.time())}.db"), sample_sales=0.55)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            desk = browser.new_page(viewport={"width": 1366, "height": 860}, device_scale_factor=1)

            desk.goto(server.url)
            desk.get_by_label("Username").fill("mei")
            desk.screenshot(path=OUT / "sign-in.png")

            sign_in(desk, server.url)
            row_c = [f"C-{n:02d}" for n in range(6, 14)]
            a = first_free(desk, row_c)
            desk.locator(f'[data-seat="{a}"]').click()
            expect(desk.locator(f'[data-seat="{a}"]')).to_have_attribute("data-state", "mine")
            b = first_free(desk, [s for s in row_c if s != a])
            desk.locator(f'[data-seat="{b}"]').click()
            expect(desk.locator(f'[data-seat="{b}"]')).to_have_attribute("data-state", "mine")
            desk.mouse.move(5, 5)
            desk.get_by_label("Card number").fill("4242 4242 4242 4242")
            desk.screenshot(path=OUT / "seat-map-hold.png")

            desk.get_by_label("Card number").fill("4000 0000 0000 0002")
            desk.locator("#pay").click()
            expect(desk.locator("#notice")).to_be_visible()
            desk.screenshot(path=OUT / "payment-declined.png")

            taken = desk.evaluate("[...document.querySelectorAll('[data-state=taken]')].map(e => e.dataset.seat)")
            desk.locator(f'[data-seat="{taken[0]}"]').click()
            expect(desk.locator("#mapError")).to_be_visible()
            desk.screenshot(path=OUT / "seat-taken-message.png")

            desk.get_by_label("Card number").fill("4242 4242 4242 4242")
            desk.locator("#pay").click()
            expect(desk.get_by_role("heading", name="My tickets")).to_be_visible()
            desk.screenshot(path=OUT / "my-tickets.png")

            phone = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                     is_mobile=True, has_touch=True)
            sign_in(phone, server.url, "arjun")
            seat = first_free(phone, [f"H-{n:02d}" for n in range(8, 16)])
            phone.locator(f'[data-seat="{seat}"]').click()
            expect(phone.locator(f'[data-seat="{seat}"]')).to_have_attribute("data-state", "mine")
            phone.screenshot(path=OUT / "phone.png")

            browser.close()
    finally:
        live_server.stop(server)

    closed = live_server.start(str(work / f"closed-{int(time.time())}.db"), sale_opens_in=3600, sample_sales=0.2)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            page = browser.new_page(viewport={"width": 1366, "height": 860})
            sign_in(page, closed.url, "siti")
            page.locator('[data-seat="A-05"]').click()
            expect(page.locator("#mapError")).to_be_visible()
            page.mouse.move(5, 5)
            page.screenshot(path=OUT / "before-sale-opens.png")
            browser.close()
    finally:
        live_server.stop(closed)
    for f in sorted(OUT.glob("*.png")):
        print(f.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
