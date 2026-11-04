"""R5 and R9: My tickets, and that tickets are private."""


def test_my_tickets_lists_what_i_bought(sign_in):
    lejie = sign_in("lejie")
    for seat in ["C-10", "C-09"]:
        lejie.hold(seat)
    lejie.checkout()
    assert [t["seat_id"] for t in lejie.tickets()] == ["C-09", "C-10"]


def test_a_ticket_can_be_fetched_by_its_owner(sign_in):
    lejie = sign_in("lejie")
    lejie.hold("C-09")
    ticket_id = lejie.checkout().json()["tickets"][0]["id"]
    response = lejie.client.get(f"/api/tickets/{ticket_id}", headers=lejie.headers)
    assert response.status_code == 200
    assert response.json()["seat_id"] == "C-09"


def test_someone_elses_ticket_looks_like_it_does_not_exist(sign_in):
    lejie, arjun = sign_in("lejie"), sign_in("arjun")
    lejie.hold("C-09")
    ticket_id = lejie.checkout().json()["tickets"][0]["id"]
    theirs = arjun.client.get(f"/api/tickets/{ticket_id}", headers=arjun.headers)
    missing = arjun.client.get(f"/api/tickets/{'0' * 32}", headers=arjun.headers)
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()
    assert arjun.tickets() == []
