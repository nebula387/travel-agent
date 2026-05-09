import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from telegram import Update

from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting travel-agent (env=%s)", settings.environment)
    from app.bot.handlers import init_application, shutdown_application
    await init_application()
    yield
    await shutdown_application()
    logger.info("travel-agent stopped")


app = FastAPI(
    title="Travel Agent",
    description="AI-powered travel planning via Telegram",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "environment": settings.environment}


@app.get("/")
async def root() -> dict:
    return {"service": "travel-agent", "version": "0.2.0"}


@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request) -> Response:
    if token != settings.secret_key:
        logger.warning("Webhook: invalid token")
        return Response(status_code=403)

    from app.bot.handlers import get_application

    try:
        bot_app = get_application()
    except RuntimeError:
        logger.error("Webhook received but bot not initialized")
        return Response(status_code=503)

    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
    except Exception:
        logger.exception("Error processing webhook update")
        return Response(status_code=500)

    return Response(status_code=200)
