"""TamiTor application bootstrap for the 360dialog transport foundation."""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI

from echo_v2.app.webhooks.dialog360 import build_router
from echo_v2.integrations.dialog360.settings import Dialog360Settings
from echo_v2.ports.bot import BotEventHandler

__all__ = ["app", "create_app"]


def create_app(handler: BotEventHandler | None = None) -> FastAPI:
    """Mount the webhook only when a business-aware handler is configured."""
    load_dotenv()
    app = FastAPI(title="TamiTor", version="0.1.0")
    if handler is not None:
        app.include_router(
            build_router(handler=handler, webhook_secret=Dialog360Settings().webhook_secret)
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
