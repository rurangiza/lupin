"""How Telegram updates reach Lupin: long polling (local) or webhook (public URL)."""

import asyncio
import hmac
import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from lupin.channels.telegram.adapter import TelegramChannel
from lupin.channels.telegram.client import TelegramClient

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/channels/telegram/webhook"
POLL_TIMEOUT_SECONDS = 30
POLL_RETRY_SECONDS = 5

router = APIRouter()


@router.post(WEBHOOK_PATH, include_in_schema=False)
async def telegram_webhook(
    request: Request,
    background: BackgroundTasks,
    secret: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
) -> dict[str, bool]:
    expected: str | None = getattr(request.app.state, "telegram_webhook_secret", None)
    channel: TelegramChannel | None = getattr(request.app.state, "telegram", None)
    if expected is None or channel is None:
        raise HTTPException(status_code=404)
    if secret is None or not hmac.compare_digest(secret, expected):
        raise HTTPException(status_code=401)
    update = await request.json()
    # Answer right away: Telegram retries deliveries that take too long.
    background.add_task(_process_safely, channel, update)
    return {"ok": True}


async def _process_safely(channel: TelegramChannel, update: dict) -> None:
    try:
        await channel.process_update(update)
    except Exception:
        logger.exception("Failed to process Telegram update %s", update.get("update_id"))


async def run_polling(client: TelegramClient, channel: TelegramChannel) -> None:
    offset: int | None = None
    webhook_cleared = False
    while True:
        try:
            if not webhook_cleared:
                # getUpdates is refused while a webhook is registered.
                await client.delete_webhook()
                webhook_cleared = True
                logger.info("Telegram long polling started")
            updates = await client.get_updates(offset, poll_seconds=POLL_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # One line per failure: network blips are routine during long polling.
            logger.warning(
                "getUpdates failed (%s: %s), retrying in %ss",
                type(e).__name__,
                e,
                POLL_RETRY_SECONDS,
            )
            await asyncio.sleep(POLL_RETRY_SECONDS)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            # One at a time keeps replies in the order messages were sent.
            await _process_safely(channel, update)


async def register_webhook(client: TelegramClient, base_url: str, secret: str) -> None:
    url = base_url.rstrip("/") + WEBHOOK_PATH
    await client.set_webhook(url, secret)
    logger.info("Telegram webhook registered at %s", url)


async def discover_quick_tunnel_url(
    metrics_url: str, timeout_seconds: float = 60.0, http: httpx.AsyncClient | None = None
) -> str:
    """Read the random *.trycloudflare.com hostname from cloudflared's metrics server."""
    owns_client = http is None
    http = http or httpx.AsyncClient(timeout=5.0)
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    try:
        while True:
            try:
                response = await http.get(metrics_url.rstrip("/") + "/quicktunnel")
                hostname = response.json().get("hostname")
                if hostname:
                    return f"https://{hostname}"
            except (httpx.HTTPError, ValueError):
                pass
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError(f"cloudflared did not report a tunnel URL at {metrics_url}")
            await asyncio.sleep(1.0)
    finally:
        if owns_client:
            await http.aclose()
