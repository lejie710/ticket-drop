"""Checks that need the real server process rather than the in-process app.

The server here runs exactly as a fan would get it: test hooks off.
"""

import socket

import pytest

from tests.support import live_server

pytestmark = pytest.mark.security


@pytest.fixture
def server(tmp_path):
    srv = live_server.start(str(tmp_path / "hardening.db"), extra_env={"TICKET_DROP_TEST_HOOKS": "0"})
    yield srv
    live_server.stop(srv)


def test_the_clock_control_route_does_not_exist(server):
    response = server.http.post("/api/_test/clock", json={"advance_ms": 600_000})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_server_software_is_not_advertised(server):
    response = server.http.get("/api/event")
    assert "server" not in {k.lower() for k in response.headers}


def non_loopback_addresses() -> list[str]:
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except socket.gaierror:
        return []
    return sorted({info[4][0] for info in infos if not info[4][0].startswith("127.")})


def test_server_listens_only_on_this_computer(server):
    """Connecting through one of this machine's network addresses must fail."""
    addresses = non_loopback_addresses()
    if not addresses:
        pytest.skip("this machine has no network address other than loopback")
    port = int(server.url.rsplit(":", 1)[1])
    for address in addresses:
        with pytest.raises(OSError):  # Refused, or no route: either way nothing answers there.
            socket.create_connection((address, port), timeout=2).close()


def test_a_foreign_host_name_is_refused(server):
    """A page on another site that rebinds its own name to 127.0.0.1 still sends its own Host header."""
    response = server.http.get("/api/event", headers={"Host": "evil.example"})
    assert response.status_code == 400
    assert server.http.get("/api/event", headers={"Host": "localhost"}).status_code == 200


def test_unknown_paths_do_not_reveal_internals(server):
    for path in ["/../app/main.py", "/.env", "/app/main.py", "/%2e%2e/serve.py"]:
        response = server.http.get(path)
        assert response.status_code == 404, path
        assert "def create_app" not in response.text
