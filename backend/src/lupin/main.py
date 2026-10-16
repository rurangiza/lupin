import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from sqlalchemy import text

from lupin.assistant import Assistant
from lupin.channels.debug.router import DEBUG_SENDER_ID
from lupin.channels.debug.router import router as debug_router
from lupin.channels.telegram import transport
from lupin.channels.telegram.adapter import TelegramChannel
from lupin.channels.telegram.client import TelegramClient
from lupin.config import Settings, TelegramMode, get_settings
from lupin.core.agent import Agent
from lupin.core.llm.base import LLMProvider
from lupin.core.llm.openai import OpenAIProvider
from lupin.core.tools.base import Tool, ToolRegistry
from lupin.core.tools.web_search import WebSearch
from lupin.domain.messages import Channel
from lupin.storage import repositories as repo
from lupin.storage.database import create_engine, create_session_factory

logger = logging.getLogger(__name__)


def build_tools(settings: Settings) -> list[Tool]:
    if settings.tavily_api_key is None:
        logger.warning("TAVILY_API_KEY is not set, web search is disabled")
        return []
    return [WebSearch(settings.tavily_api_key.get_secret_value())]


def create_app(
    settings: Settings | None = None,
    llm: LLMProvider | None = None,
    tools: list[Tool] | None = None,
    telegram_client: TelegramClient | None = None,
) -> FastAPI:
    """Build the app. Arguments other than settings exist so tests can swap in fakes."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        sessions = create_session_factory(engine)
        app.state.engine = engine

        identities: list[tuple[Channel, str]] = []
        if settings.telegram_owner_user_id is not None:
            identities.append((Channel.TELEGRAM, str(settings.telegram_owner_user_id)))
        if settings.debug_api_enabled:
            identities.append((Channel.DEBUG, DEBUG_SENDER_ID))
        async with sessions() as session:
            await repo.ensure_owner(session, settings.owner_name, identities)

        agent = Agent(
            llm=llm
            or OpenAIProvider(settings.openai_api_key.get_secret_value(), settings.openai_model),
            tools=ToolRegistry(
                tools if tools is not None else build_tools(settings),
                timeout_seconds=settings.tool_timeout_seconds,
            ),
            max_tool_rounds=settings.max_tool_rounds,
        )
        assistant = Assistant(
            agent,
            sessions,
            owner_name=settings.owner_name,
            timezone=settings.owner_timezone,
            history_limit=settings.history_limit,
        )
        if settings.debug_api_enabled:
            app.state.debug_assistant = assistant

        background: list[asyncio.Task] = []
        client = None
        if settings.telegram_mode is not TelegramMode.DISABLED:
            client = telegram_client or TelegramClient(
                settings.telegram_bot_token.get_secret_value()
            )
            channel = TelegramChannel(client, assistant)
            app.state.telegram = channel
            if settings.telegram_mode is TelegramMode.POLLING:
                background.append(asyncio.create_task(transport.run_polling(client, channel)))
            else:
                secret = settings.telegram_webhook_secret.get_secret_value()
                app.state.telegram_webhook_secret = secret
                background.append(asyncio.create_task(_register_webhook(settings, client, secret)))

        logger.info("Lupin started (telegram: %s)", settings.telegram_mode)
        try:
            yield
        finally:
            for task in background:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if client is not None and telegram_client is None:
                await client.aclose()
            await engine.dispose()

    app = FastAPI(title="Lupin", lifespan=lifespan)
    app.include_router(transport.router)
    if settings.debug_api_enabled:
        app.include_router(debug_router)

    @app.get("/healthz", tags=["ops"])
    async def healthz(request: Request, response: Response) -> dict[str, str]:
        try:
            async with request.app.state.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            logger.exception("Health check failed")
            response.status_code = 503
            return {"status": "unhealthy"}
        return {"status": "ok"}

    return app


async def _register_webhook(settings: Settings, client: TelegramClient, secret: str) -> None:
    # Runs in the background so a slow tunnel does not block startup.
    while True:
        try:
            base_url = settings.public_base_url or await transport.discover_quick_tunnel_url(
                settings.cloudflared_metrics_url
            )
            await transport.register_webhook(client, base_url, secret)
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Webhook registration failed, retrying in 10s")
            await asyncio.sleep(10)


def app_factory() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # httpx logs request URLs, and Telegram puts the bot token in the URL.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return create_app()
