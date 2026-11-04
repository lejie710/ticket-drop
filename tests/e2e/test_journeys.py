"""Browser tests: what a fan sees and does, through the real UI and server."""

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

SUCCESS = "4242 4242 4242 4242"
DECLINE = "4000 0000 0000 0002"


def seat(page, seat_id):
    return page.locator(f'[data-seat="{seat_id}"]')


def test_fan_holds_two_seats_and_pays(signed_in):
    """The main journey (R5, R11)."""
    page = signed_in()
    seat(page, "C-09").click()
    expect(seat(page, "C-09")).to_have_attribute("data-state", "mine")
    seat(page, "C-10").click()
    expect(seat(page, "C-10")).to_have_attribute("data-state", "mine")
    stub = page.get_by_role("complementary", name="Your held seats")
    expect(stub).to_contain_text("Row C, seat 9")
    expect(stub).to_contain_text("Row C, seat 10")
    expect(page.get_by_role("button", name="Pay RM 776")).to_be_enabled()
    expect(page.locator("#timer")).to_have_text(re.compile(r"^[45]:\d\d$"))

    page.get_by_label("Card number").fill(SUCCESS)
    page.get_by_role("button", name="Pay RM 776").click()

    expect(page.get_by_role("heading", name="My tickets")).to_be_visible()
    expect(page.get_by_role("status")).to_have_text("Payment complete. 2 tickets are below.")
    expect(page.locator(".ticket")).to_have_count(2)
    expect(page.locator(".ticket").first).to_contain_text("Row C, seat 9")


def test_declined_card_keeps_the_seats(signed_in):
    """R6 as the fan experiences it."""
    page = signed_in()
    seat(page, "D-05").click()
    expect(seat(page, "D-05")).to_have_attribute("data-state", "mine")
    page.get_by_label("Card number").fill(DECLINE)
    page.get_by_role("button", name="Pay RM 388").click()
    expect(page.locator("#notice")).to_have_text("The card was declined. Your seats are still held.")
    expect(seat(page, "D-05")).to_have_attribute("data-state", "mine")
    expect(page.get_by_role("button", name="Pay RM 388")).to_be_enabled()


def test_pressing_enter_twice_sends_one_payment(signed_in, server):
    """Found by review: Enter in the card field submitted again while a payment was in flight.

    The server would refuse the duplicate, so the database alone cannot show the bug.
    The page must not send it, and must not unlock the seats mid-payment.
    """
    page = signed_in()
    seat(page, "D-07").click()
    expect(seat(page, "D-07")).to_have_attribute("data-state", "mine")
    sent = []
    page.on("request", lambda r: sent.append(r) if r.method == "POST" and r.url.endswith("/api/checkout") else None)
    page.get_by_label("Card number").fill("4000 0000 0000 0408")  # The gateway takes 0.5 s to time out here.
    page.get_by_label("Card number").press("Enter")
    page.get_by_label("Card number").press("Enter")
    expect(page.locator("#notice")).to_have_text("The payment service did not answer. You were not charged.")
    assert len(sent) == 1


def test_seat_taken_while_the_map_was_open(signed_in, server):
    """The map is a few seconds old; someone else gets the seat first."""
    page = signed_in()
    expect(seat(page, "E-07")).to_have_attribute("data-state", "available")
    other = server.login("arjun")
    server.http.post("/api/hold/seats", json={"seat_id": "E-07"}, headers=other).raise_for_status()
    with page.expect_request(lambda r: r.method == "GET" and r.url.endswith("/api/seats"), timeout=1500):
        # The page must re-read the map straight after the refusal, not wait for its 4-second poll.
        # (Tightened after fault injection; counting the request cannot be satisfied by the poll by luck.)
        seat(page, "E-07").click()
    expect(page.locator("#mapError")).to_have_text("Seat E-07 has just been taken.")
    expect(seat(page, "E-07")).to_have_attribute("data-state", "taken")


def test_fifth_seat_shows_the_limit(signed_in):
    """R3 as the fan experiences it."""
    page = signed_in()
    for n in range(1, 5):
        seat(page, f"F-0{n}").click()
        expect(seat(page, f"F-0{n}")).to_have_attribute("data-state", "mine")
    seat(page, "F-05").click()
    expect(page.locator("#mapError")).to_have_text("You can hold up to 4 tickets.")
    expect(seat(page, "F-05")).to_have_attribute("data-state", "available")


def test_expired_hold_is_explained_and_seats_return(signed_in, server):
    """R4: the server clock is moved past the expiry; the page notices on its next refresh."""
    page = signed_in()
    seat(page, "G-03").click()
    expect(seat(page, "G-03")).to_have_attribute("data-state", "mine")
    server.advance_clock(300_000)
    expect(page.locator("#notice")).to_have_text("Your hold ended and the seats went back on sale.", timeout=10_000)
    expect(seat(page, "G-03")).to_have_attribute("data-state", "available")
    expect(page.get_by_role("button", name="Pay")).to_be_disabled()


def test_seats_can_be_chosen_with_the_keyboard_only(signed_in):
    page = signed_in()
    page.locator('[data-seat][tabindex="0"]').focus()
    focused = page.evaluate("document.activeElement.dataset.seat")
    assert focused == "A-01"
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowDown")
    target = page.evaluate("document.activeElement.dataset.seat")
    assert target.startswith("B-")
    page.keyboard.press("Enter")
    expect(seat(page, target)).to_have_attribute("data-state", "mine")
    expect(seat(page, target)).to_have_attribute("aria-pressed", "true")


def test_tabbing_into_the_map_shows_a_focus_ring(signed_in):
    """Found by review: focus reached a seat with Tab but nothing on screen showed it."""
    page = signed_in()
    page.get_by_role("button", name="Sign out").focus()
    page.keyboard.press("Tab")
    focused = page.locator("[data-seat]:focus")
    # Within 1 s: the page re-renders every 4 s, which must not be what adds the ring.
    expect(focused).to_have_class(re.compile(r"(^|\s)focused(\s|$)"), timeout=1000)
    ring = focused.evaluate("el => getComputedStyle(el).stroke")
    other = page.locator('[data-seat="T-01"]').evaluate("el => getComputedStyle(el).stroke")
    assert ring != other


def test_enter_after_a_click_acts_on_the_clicked_seat(signed_in):
    """Found by review: Enter acted on the old tab stop instead of the seat just clicked."""
    page = signed_in()
    seat(page, "F-05").click()
    expect(seat(page, "F-05")).to_have_attribute("data-state", "mine")
    page.keyboard.press("Enter")
    expect(seat(page, "F-05")).to_have_attribute("data-state", "available")
    expect(page.locator('[data-state="mine"]')).to_have_count(0)


def test_retry_after_a_server_error_reuses_the_payment_key(signed_in):
    """DEF-012: after a 500 the page must keep its key, so a retry can finish the first attempt.

    The server's own recovery (a repeated key finishes settling) is tested in
    tests/api/test_checkout_recovery.py. This test checks the page's half: the first
    answer is a 500, and the retry must carry the same Idempotency-Key.
    """
    page = signed_in()
    seat(page, "D-03").click()
    expect(seat(page, "D-03")).to_have_attribute("data-state", "mine")
    keys = []

    def first_answer_lost(route):
        keys.append(route.request.headers.get("idempotency-key"))
        if len(keys) == 1:
            route.fulfill(status=500, json={"error": {"code": "server_error", "message": "Something went wrong."}})
        else:
            route.continue_()

    page.route("**/api/checkout", first_answer_lost)
    page.get_by_label("Card number").fill(SUCCESS)
    page.get_by_role("button", name="Pay RM 388").click()
    expect(page.locator("#notice")).to_have_text("Something went wrong.")
    page.get_by_role("button", name="Pay RM 388").click()
    expect(page.get_by_role("heading", name="My tickets")).to_be_visible()
    expect(page.locator(".ticket")).to_have_count(1)
    assert len(keys) == 2 and keys[0] == keys[1]


def test_a_new_seat_clears_an_old_payment_message(signed_in):
    page = signed_in()
    seat(page, "D-05").click()
    expect(seat(page, "D-05")).to_have_attribute("data-state", "mine")
    page.get_by_label("Card number").fill(DECLINE)
    page.get_by_role("button", name="Pay RM 388").click()
    expect(page.locator("#notice")).to_be_visible()
    seat(page, "D-06").click()
    expect(seat(page, "D-06")).to_have_attribute("data-state", "mine")
    expect(page.locator("#notice")).to_be_hidden()


def test_wrong_password_is_explained(page, server):
    page.goto(server.url)
    page.get_by_label("Username").fill("lejie")
    page.get_by_label("Password").fill("wrong")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("alert")).to_have_text("The username or password is wrong.")


def test_before_the_sale_opens(page, start_server):
    """R1: the countdown shows and holding is refused with an explanation."""
    srv = start_server(sale_opens_in=3600)
    page.goto(srv.url)
    page.get_by_label("Username").fill("lejie")
    page.get_by_label("Password").fill("demo-pass")
    page.get_by_role("button", name="Sign in").click()
    expect(page.locator("#saleState")).to_contain_text(re.compile(r"Sale opens in \d+:\d\d"))
    seat(page, "A-01").click()
    expect(page.locator("#mapError")).to_have_text("The sale has not opened yet.")


def test_phone_layout_docks_the_payment_strip(page, signed_in):
    page.set_viewport_size({"width": 390, "height": 844})
    signed_in()
    page.locator(".map-scroll").evaluate("el => el.scrollLeft = (el.scrollWidth - el.clientWidth) / 2")
    seat(page, "C-09").click()
    expect(seat(page, "C-09")).to_have_attribute("data-state", "mine")
    pay = page.get_by_role("button", name="Pay RM 388")
    expect(pay).to_be_in_viewport()
    expect(page.locator("#phoneHeld")).to_have_text("Held: C9. Total RM 388. Tap a seat again to release it.")
    box = page.locator("#stub").bounding_box()
    assert box["y"] + box["height"] == pytest.approx(844, abs=2)  # Docked to the bottom edge.
