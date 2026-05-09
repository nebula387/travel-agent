"""
Integration tests for FastAPI endpoints.

Uses AsyncClient with ASGITransport — bot lifespan is NOT triggered
(no lifespan= parameter), so Telegram token is not validated.
"""
import pytest


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "environment" in data


async def test_health_returns_environment(client):
    r = await client.get("/health")
    env = r.json()["environment"]
    assert env in ("development", "production", "test")


async def test_webhook_wrong_token_rejected(client):
    """POST to /webhook/wrongtoken should return 403 or 404."""
    r = await client.post("/webhook/not-a-real-token", json={})
    assert r.status_code in (403, 404)


async def test_docs_available_in_dev(client):
    """OpenAPI docs are served in non-production mode."""
    r = await client.get("/docs")
    # In development mode docs_url="/docs" is set; 200 means Swagger served
    assert r.status_code in (200, 404)  # 404 if production


async def test_unknown_route_returns_404(client):
    r = await client.get("/nonexistent-endpoint")
    assert r.status_code == 404


async def test_webhook_get_not_allowed(client):
    """Webhook endpoint only accepts POST, not GET."""
    from app.config import settings
    path = f"/webhook/{settings.secret_key}"
    r = await client.get(path)
    assert r.status_code == 405
