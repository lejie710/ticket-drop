"""Checks that need the real server process rather than the in-process app."""

import pytest

from tests.support import live_server

pytestmark = pytest.mark.security


@pytest.fixture
def server(tmp_path):
    srv = live_server.start(str(tmp_path / "hardening.db"))
    yield srv
    live_server.stop(srv)


def test_server_software_is_not_advertised(server):
    response = server.http.get("/api/event")
    assert "server" not in {k.lower() for k in response.headers}


def test_server_listens_only_on_this_computer(server):
    assert server.url.startswith("http://127.0.0.1:")


def test_unknown_paths_do_not_reveal_internals(server):
    for path in ["/../app/main.py", "/.env", "/app/main.py", "/%2e%2e/serve.py"]:
        response = server.http.get(path)
        assert response.status_code == 404, path
        assert "def create_app" not in response.text
