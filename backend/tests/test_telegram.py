import json

import httpx
import pytest

from lupin.channels.telegram.adapter import UNSUPPORTED_REPLY, TelegramChannel, parse_update
from lupin.channels.telegram.client import TelegramClient
from lupin.channels.telegram.formatting import markdown_to_telegram_html, split_message
from lupin.channels.telegram.transport import discover_quick_tunnel_url
from lupin.core.llm.base import LLMTextDelta
from lupin.domain.messages import Channel
from tests.conftest import OWNER_TELEGRAM_ID, FakeLLM, make_assistant


class FakeBotAPI:
    """Records Bot API calls. Can reject HTML to exercise the plain-text fallback."""

    def __init__(self, reject_html: bool = False) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.reject_html = reject_html

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.content or b"{}")
        self.calls.append((method, payload))
        if method == "sendMessage" and self.reject_html and payload.get("parse_mode"):
            return httpx.Response(
                400, json={"ok": False, "error_code": 400, "description": "can't parse entities"}
            )
        return httpx.Response(200, json={"ok": True, "result": True})

    def client(self) -> TelegramClient:
        return TelegramClient(
            "TOKEN", http=httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        )

    def sent_texts(self) -> list[str]:
        return [p["text"] for m, p in self.calls if m == "sendMessage"]


def update(text: str | None, sender: str = OWNER_TELEGRAM_ID, update_id: int = 1) -> dict:
    message = {"message_id": 1, "from": {"id": int(sender)}, "chat": {"id": 42}}
    if text is not None:
        message["text"] = text
    return {"update_id": update_id, "message": message}


def test_parse_update_builds_an_envelope():
    inbound = parse_update(update("hello", update_id=7))

    assert inbound.channel is Channel.TELEGRAM
    assert inbound.sender_id == OWNER_TELEGRAM_ID
    assert inbound.chat_id == "42"
    assert inbound.event_id == "telegram:7"


def test_parse_update_ignores_non_message_updates():
    assert parse_update({"update_id": 1, "edited_message": {}}) is None


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        ("**bold** and *it*", "<b>bold</b> and <i>it</i>"),
        ("a < b & c", "a &lt; b &amp; c"),
        ("`x<y`", "<code>x&lt;y</code>"),
        ("```py\nif a**b**:\n```", "<pre>if a**b**:\n</pre>"),
        ("[site](https://e.com/?a=1&b=2)", '<a href="https://e.com/?a=1&amp;b=2">site</a>'),
        ("## Title", "<b>Title</b>"),
        ("2 * 3 * 4", "2 * 3 * 4"),
    ],
)
def test_markdown_to_telegram_html(markdown, expected):
    assert markdown_to_telegram_html(markdown) == expected


def test_split_message_respects_limit_and_prefers_paragraphs():
    text = ("a" * 30 + "\n\n") * 5

    chunks = split_message(text, limit=70)

    assert all(len(c) <= 70 for c in chunks)
    assert "".join(chunks).replace("\n", "") == "a" * 150


async def test_owner_message_gets_a_formatted_reply(sessions, owner_id):
    api = FakeBotAPI()
    channel = TelegramChannel(
        api.client(), make_assistant(sessions, FakeLLM([LLMTextDelta("**Hi**")]))
    )

    await channel.process_update(update("hello"))

    assert ("sendChatAction", {"chat_id": "42", "action": "typing"}) in api.calls
    sent = [p for m, p in api.calls if m == "sendMessage"]
    assert sent[0]["text"] == "<b>Hi</b>"
    assert sent[0]["parse_mode"] == "HTML"


async def test_rejected_html_falls_back_to_plain_text(sessions, owner_id):
    api = FakeBotAPI(reject_html=True)
    channel = TelegramChannel(
        api.client(), make_assistant(sessions, FakeLLM([LLMTextDelta("**Hi**")]))
    )

    await channel.process_update(update("hello"))

    assert api.sent_texts() == ["<b>Hi</b>", "**Hi**"]


async def test_stranger_gets_no_reply_and_no_typing(sessions, owner_id):
    api = FakeBotAPI()
    channel = TelegramChannel(api.client(), make_assistant(sessions, FakeLLM()))

    await channel.process_update(update("hello", sender="999"))

    assert api.calls == []


async def test_non_text_message_gets_a_notice(sessions, owner_id):
    api = FakeBotAPI()
    channel = TelegramChannel(api.client(), make_assistant(sessions, FakeLLM()))

    await channel.process_update(update(None))

    assert api.sent_texts() == [UNSUPPORTED_REPLY]


async def test_quick_tunnel_url_is_read_from_cloudflared_metrics():
    responses = iter([{"hostname": ""}, {"hostname": "abc.trycloudflare.com"}])
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=next(responses)))
    )

    url = await discover_quick_tunnel_url("http://cloudflared:2000", http=http)

    assert url == "https://abc.trycloudflare.com"
