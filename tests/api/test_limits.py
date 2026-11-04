"""R3: at most four seats per account, counting held seats and owned tickets.

Boundary value analysis: 4 is the last valid value, 5 the first invalid one.
"""

import pytest


@pytest.mark.parametrize("count", [1, 3, 4])
def test_up_to_four_seats_can_be_held(sign_in, count):
    lejie = sign_in("lejie")
    for n in range(1, count + 1):
        assert lejie.hold(f"E-{n:02d}").status_code == 200
    assert len(lejie.current_hold()["seats"]) == count


def test_the_fifth_seat_is_refused(sign_in):
    lejie = sign_in("lejie")
    for n in range(1, 5):
        lejie.hold(f"E-{n:02d}")
    response = lejie.hold("E-05")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "limit_reached"
    assert response.json()["error"]["message"] == "Each account can have up to 4 tickets. You hold 4."
    assert len(lejie.current_hold()["seats"]) == 4


def test_owned_tickets_count_towards_the_limit(sign_in):
    lejie = sign_in("lejie")
    for seat in ["E-01", "E-02", "E-03"]:
        lejie.hold(seat)
    assert lejie.checkout().status_code == 200
    assert lejie.hold("F-01").status_code == 200  # 3 owned + 1 held = 4
    refused = lejie.hold("F-02").json()["error"]
    assert refused["code"] == "limit_reached"
    # The message names the owned tickets; "you can hold 4" would be wrong while holding 1.
    assert refused["message"] == "Each account can have up to 4 tickets. You already own 3 and hold 1."


def test_releasing_a_seat_frees_room_under_the_limit(sign_in):
    lejie = sign_in("lejie")
    for n in range(1, 5):
        lejie.hold(f"E-{n:02d}")
    lejie.unhold("E-01")
    assert lejie.hold("E-05").status_code == 200


def test_the_limit_is_per_account(sign_in):
    lejie, arjun = sign_in("lejie"), sign_in("arjun")
    for n in range(1, 5):
        lejie.hold(f"E-{n:02d}")
    assert arjun.hold("E-05").status_code == 200
