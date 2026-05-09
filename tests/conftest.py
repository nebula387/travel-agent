"""
Test configuration and shared fixtures.

Tests run without real external services:
- Redis: mocked via unittest.mock
- PostgreSQL: SharedContext PostgreSQL path silently skipped (DEBUG log)
- Telegram bot token: placeholder → init_application() skips PTB setup
- LLM (Gemini/Groq): patched to return fixed strings
- HTTP APIs: intercepted via pytest-httpx HTTPXMock
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport


# ── Environment patches applied session-wide ─────────────────────────────────

@pytest.fixture(autouse=True, scope="session")
def patch_redis():
    """Replace aioredis client with an in-memory AsyncMock for all tests."""
    mock_redis = AsyncMock()
    mock_redis.hget = AsyncMock(return_value=None)
    mock_redis.hset = AsyncMock(return_value=True)
    mock_redis.hgetall = AsyncMock(return_value={})
    mock_redis.expire = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock(return_value=1)
    mock_redis.scan_iter = MagicMock(return_value=iter([]))

    with patch("app.memory.context.get_redis", return_value=mock_redis):
        yield mock_redis


@pytest.fixture(autouse=True, scope="session")
def patch_llm():
    """Prevent real Gemini/Groq calls in all tests."""
    with patch(
        "app.agents.base.BaseAgent._llm",
        new=AsyncMock(return_value="[LLM mocked response]"),
    ):
        yield


# ── FastAPI / HTTP client ─────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def app():
    from app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
async def client(app):
    """Async HTTP client against the FastAPI app (no lifespan)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── Shared context mock ───────────────────────────────────────────────────────

@pytest.fixture
def mock_ctx():
    """SharedContext stub that stores values in a plain dict."""
    store: dict = {
        "passport_country": "Россия",
        "monthly_budget": 1500,
    }
    ctx = AsyncMock()
    ctx.read = AsyncMock(side_effect=lambda k, d=None: store.get(k, d))
    ctx.write = AsyncMock(side_effect=lambda k, v, **kw: store.update({k: v}))
    ctx.get = ctx.read
    ctx.set = ctx.write
    return ctx
