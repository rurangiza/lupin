from typing import Any

import httpx


class TelegramAPIError(Exception):
    def __init__(self, method: str, description: str, error_code: int | None) -> None:
        super().__init__(f"Telegram {method} failed ({error_code}): {description}")
        self.description = description
        self.error_code = error_code


class TelegramClient:
    """Thin async wrapper over the few Bot API methods Lupin uses."""

    def __init__(self, token: str, http: httpx.AsyncClient | None = None) -> None:
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=60.0))

    async def call(self, method: str, **params: Any) -> Any:
        payload = {k: v for k, v in params.items() if v is not None}
        response = await self._http.post(f"{self._base_url}/{method}", json=payload)
        body = response.json()
        if not body.get("ok"):
            raise TelegramAPIError(method, body.get("description", ""), body.get("error_code"))
        return body["result"]

    async def get_updates(self, offset: int | None, poll_seconds: int) -> list[dict[str, Any]]:
        return await self.call(
            "getUpdates", offset=offset, timeout=poll_seconds, allowed_updates=["message"]
        )

    async def send_message(self, chat_id: str, text: str, parse_mode: str | None = None) -> None:
        await self.call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            link_preview_options={"is_disabled": True},
        )

    async def send_typing(self, chat_id: str) -> None:
        await self.call("sendChatAction", chat_id=chat_id, action="typing")

    async def set_webhook(self, url: str, secret_token: str) -> None:
        await self.call(
            "setWebhook",
            url=url,
            secret_token=secret_token,
            allowed_updates=["message"],
            drop_pending_updates=False,
        )

    async def delete_webhook(self) -> None:
        await self.call("deleteWebhook", drop_pending_updates=False)

    async def aclose(self) -> None:
        await self._http.aclose()
