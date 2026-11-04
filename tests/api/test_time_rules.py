"""R1 and R4: the sale opening and hold expiry, tested on their exact boundaries."""

from tests.conftest import T0

HOLD_MS = 300_000


def test_hold_is_still_valid_one_millisecond_before_expiry(sign_in, clock):
    mei, arjun = sign_in("mei"), sign_in("arjun")
    mei.hold("C-09")
    clock.advance(HOLD_MS - 1)
    assert mei.seat_states()["C-09"] == "mine"
    assert arjun.hold("C-09").json()["error"]["code"] == "seat_taken"


def test_hold_ends_exactly_at_expiry(sign_in, clock):
    mei, arjun = sign_in("mei"), sign_in("arjun")
    mei.hold("C-09")
    clock.advance(HOLD_MS)
    assert mei.current_hold() is None
    assert arjun.hold("C-09").status_code == 200


def test_expiry_is_reported_from_the_first_seat(sign_in):
    hold = sign_in("mei").hold("C-09").json()["hold"]
    assert hold["expires_ms"] - hold["created_ms"] == HOLD_MS


def test_adding_seats_does_not_extend_the_hold(sign_in, clock):
    mei = sign_in("mei")
    first = mei.hold("C-09").json()["hold"]["expires_ms"]
    clock.advance(200_000)
    later = mei.hold("C-10").json()["hold"]["expires_ms"]
    assert later == first
    clock.advance(HOLD_MS - 200_000)
    assert mei.current_hold() is None  # Both seats expire together, at the original time.


def test_paying_after_expiry_is_refused(sign_in, clock, query):
    mei = sign_in("mei")
    mei.hold("C-09")
    clock.advance(HOLD_MS)
    response = mei.checkout()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_hold"
    assert query("SELECT COUNT(*) AS n FROM charges") == [{"n": 0}]


def test_seats_cannot_be_held_before_the_sale_opens(make_client, sign_in, clock):
    client = make_client(sale_opens_at_ms=T0 + 60_000)
    mei = sign_in("mei", client)
    response = mei.hold("C-09")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "sale_not_open"
    clock.advance(59_999)
    assert mei.hold("C-09").json()["error"]["code"] == "sale_not_open"


def test_the_opening_instant_itself_is_open(make_client, sign_in, clock):
    client = make_client(sale_opens_at_ms=T0 + 60_000)
    mei = sign_in("mei", client)
    clock.advance(60_000)
    assert mei.hold("C-09").status_code == 200


def test_event_reports_whether_the_sale_is_open(make_client, clock):
    client = make_client(sale_opens_at_ms=T0 + 60_000)
    assert client.get("/api/event").json()["sale_open"] is False
    clock.advance(60_000)
    assert client.get("/api/event").json()["sale_open"] is True
