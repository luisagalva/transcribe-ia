import pytest
import fakeredis


@pytest.fixture
def fake_server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest.fixture
async def fake_redis(fake_server: fakeredis.FakeServer):
    r = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)
    yield r
    await r.aclose()
