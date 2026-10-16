import asyncio
import contextlib
import logging
from typing import Any

from lupin.assistant import Assistant
from lupin.channels.telegram.client import TelegramAPIError, TelegramClient
from lupin.channels.telegram.formatting import markdown_to_telegram_html, split_message
from lupin.domain.messages import Capabilities, Channel, InboundMessage, OutboundMessage

logger = logging.getLogger(__name__)

CAPABILITIES = Capabilities(markdown=True, max_reply_chars=4096)
UNSUPPORTED_REPLY = "I can only read text messages for now."
TYPING_REFRESH_SECONDS = 4.0  # Telegram shows "typing…" for about 5 seconds.


def parse_update(update: dict[str, Any]) -> InboundMessage | None:
    message = update.get("message")
    if not message or "from" not in message:
        return None
    return InboundMessage(
        channel=Channel.TELEGRAM,
        sender_id=str(message["from"]["id"]),
        chat_id=str(message["chat"]["id"]),
        text=message.get("text", ""),
        event_id=f"telegram:{update['update_id']}",
        capabilities=CAPABILITIES,
    )


class TelegramChannel:
    channel = Channel.TELEGRAM

    def __init__(self, client: TelegramClient, assistant: Assistant) -> None:
        self._client = client
        self._assistant = assistant

    async def process_update(self, update: dict[str, Any]) -> None:
        inbound = parse_update(update)
        # Unknown senders get no reply and no typing indicator: the bot stays invisible.
        if inbound is None or not await self._assistant.is_known(inbound):
            return
        if not inbound.text:
            # Photos, voice notes, stickers: acknowledge instead of staying silent.
            await self.send(OutboundMessage(Channel.TELEGRAM, inbound.chat_id, UNSUPPORTED_REPLY))
            return

        typing = asyncio.create_task(self._keep_typing(inbound.chat_id))
        try:
            reply = await self._assistant.handle(inbound)
        finally:
            typing.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await typing
        if reply is not None:
            await self.send(OutboundMessage(Channel.TELEGRAM, inbound.chat_id, reply.text or "…"))

    async def send(self, message: OutboundMessage) -> None:
        for chunk in split_message(message.text):
            try:
                await self._client.send_message(
                    message.chat_id, markdown_to_telegram_html(chunk), parse_mode="HTML"
                )
            except TelegramAPIError as e:
                if e.error_code != 400:
                    raise
                logger.info("Telegram rejected formatted text, sending plain: %s", e)
                await self._client.send_message(message.chat_id, chunk)

    async def _keep_typing(self, chat_id: str) -> None:
        while True:
            try:
                await self._client.send_typing(chat_id)
            except Exception:
                logger.debug("Could not send typing indicator", exc_info=True)
            await asyncio.sleep(TYPING_REFRESH_SECONDS)
