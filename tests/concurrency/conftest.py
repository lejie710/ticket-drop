import pytest

from tests.support import live_server


@pytest.fixture
def server(tmp_path):
    srv = live_server.start(str(tmp_path / "race.db"))
    yield srv
    live_server.stop(srv)
