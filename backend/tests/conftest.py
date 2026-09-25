from __future__ import annotations

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


@pytest.fixture
def gateway_with_fake_redis(fake_server: fakeredis.FakeServer):
    """
    Yields the FastAPI app with its module-level _redis patched to a
    FakeAsyncRedis backed by the shared fake_server fixture.

    The original value is restored after the test so module state does not
    bleed between tests.
    """
    from backend.gateway import main as gw

    fake_r = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)
    original = gw._redis
    gw._redis = fake_r
    yield gw.app
    gw._redis = original
