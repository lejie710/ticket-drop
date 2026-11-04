"""R2, R11, R13: holding and releasing seats, and what the seat map shows."""


def test_held_seat_shows_as_mine_to_me_and_taken_to_others(sign_in):
    lejie, arjun = sign_in("lejie"), sign_in("arjun")
    response = lejie.hold("C-09")
    assert response.status_code == 200
    assert [s["id"] for s in response.json()["hold"]["seats"]] == ["C-09"]
    assert lejie.seat_states()["C-09"] == "mine"
    assert arjun.seat_states()["C-09"] == "taken"


def test_a_seat_held_by_someone_else_cannot_be_held(sign_in):
    lejie, arjun = sign_in("lejie"), sign_in("arjun")
    assert lejie.hold("C-09").status_code == 200
    response = arjun.hold("C-09")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "seat_taken"
    assert arjun.current_hold() is None  # The failed attempt left no empty hold behind.


def test_holding_the_same_seat_twice_changes_nothing(sign_in):
    lejie = sign_in("lejie")
    first = lejie.hold("C-09").json()["hold"]
    second = lejie.hold("C-09").json()["hold"]
    assert first == second


def test_releasing_one_seat_makes_it_available_at_once(sign_in):
    lejie, arjun = sign_in("lejie"), sign_in("arjun")
    lejie.hold("C-09")
    lejie.hold("C-10")
    response = lejie.unhold("C-09")
    assert response.status_code == 200
    assert [s["id"] for s in response.json()["hold"]["seats"]] == ["C-10"]
    assert arjun.hold("C-09").status_code == 200


def test_releasing_the_last_seat_closes_the_hold(sign_in, query):
    lejie = sign_in("lejie")
    lejie.hold("C-09")
    assert lejie.unhold("C-09").json()["hold"] is None
    assert query("SELECT status FROM holds") == [{"status": "released"}]


def test_releasing_the_whole_hold(sign_in):
    lejie, arjun = sign_in("lejie"), sign_in("arjun")
    for seat in ["C-09", "C-10", "C-11"]:
        lejie.hold(seat)
    assert lejie.release_all().status_code == 204
    assert lejie.current_hold() is None
    assert all(arjun.seat_states()[s] == "available" for s in ["C-09", "C-10", "C-11"])


def test_unknown_seat(sign_in):
    response = sign_in("lejie").hold("A-99")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "seat_not_found"


def test_seat_map_has_510_seats_in_three_categories(sign_in):
    lejie = sign_in("lejie")
    seats = lejie.client.get("/api/seats", headers=lejie.headers).json()["seats"]
    assert len(seats) == 510
    assert {s["tier"] for s in seats} == {1, 2, 3}
    assert {s["price_cents"] for s in seats} == {38800, 26800, 16800}
