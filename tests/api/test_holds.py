"""R2, R11, R13: holding and releasing seats, and what the seat map shows."""


def test_held_seat_shows_as_mine_to_me_and_taken_to_others(sign_in):
    mei, arjun = sign_in("mei"), sign_in("arjun")
    response = mei.hold("C-09")
    assert response.status_code == 200
    assert [s["id"] for s in response.json()["hold"]["seats"]] == ["C-09"]
    assert mei.seat_states()["C-09"] == "mine"
    assert arjun.seat_states()["C-09"] == "taken"


def test_a_seat_held_by_someone_else_cannot_be_held(sign_in):
    mei, arjun = sign_in("mei"), sign_in("arjun")
    assert mei.hold("C-09").status_code == 200
    response = arjun.hold("C-09")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "seat_taken"
    assert arjun.current_hold() is None  # The failed attempt left no empty hold behind.


def test_holding_the_same_seat_twice_changes_nothing(sign_in):
    mei = sign_in("mei")
    first = mei.hold("C-09").json()["hold"]
    second = mei.hold("C-09").json()["hold"]
    assert first == second


def test_releasing_one_seat_makes_it_available_at_once(sign_in):
    mei, arjun = sign_in("mei"), sign_in("arjun")
    mei.hold("C-09")
    mei.hold("C-10")
    response = mei.unhold("C-09")
    assert response.status_code == 200
    assert [s["id"] for s in response.json()["hold"]["seats"]] == ["C-10"]
    assert arjun.hold("C-09").status_code == 200


def test_releasing_the_last_seat_closes_the_hold(sign_in, query):
    mei = sign_in("mei")
    mei.hold("C-09")
    assert mei.unhold("C-09").json()["hold"] is None
    assert query("SELECT status FROM holds") == [{"status": "released"}]


def test_releasing_the_whole_hold(sign_in):
    mei, arjun = sign_in("mei"), sign_in("arjun")
    for seat in ["C-09", "C-10", "C-11"]:
        mei.hold(seat)
    assert mei.release_all().status_code == 204
    assert mei.current_hold() is None
    assert all(arjun.seat_states()[s] == "available" for s in ["C-09", "C-10", "C-11"])


def test_cannot_release_a_seat_you_do_not_hold(sign_in):
    mei, arjun = sign_in("mei"), sign_in("arjun")
    mei.hold("C-09")
    arjun.hold("D-01")
    response = arjun.unhold("C-09")
    assert response.status_code == 404
    assert mei.seat_states()["C-09"] == "mine"


def test_unknown_seat(sign_in):
    response = sign_in("mei").hold("A-99")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "seat_not_found"


def test_seat_map_has_510_seats_in_three_categories(sign_in):
    seats = sign_in("mei").client.get("/api/seats", headers=sign_in("mei").headers).json()["seats"]
    assert len(seats) == 510
    assert {s["tier"] for s in seats} == {1, 2, 3}
    assert {s["price_cents"] for s in seats} == {38800, 26800, 16800}
