import pytest

from tests.support import live_server


@pytest.fixture
def start_server(tmp_path):
    started = []

    def _start(**kwargs):
        server = live_server.start(str(tmp_path / f"e2e{len(started)}.db"), **kwargs)
        started.append(server)
        return server

    yield _start
    for server in started:
        live_server.stop(server)


@pytest.fixture
def server(start_server):
    return start_server()


@pytest.fixture
def signed_in(page, server):
    """A browser page signed in as Le Jie, on the seat map."""
    def _signed_in(username="lejie", srv=None):
        srv = srv or server
        page.goto(srv.url)
        page.get_by_label("Username").fill(username)
        page.get_by_label("Password").fill("demo-pass")
        page.get_by_role("button", name="Sign in").click()
        page.locator('[data-seat="A-01"]').wait_for()
        return page
    return _signed_in
