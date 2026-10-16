import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from lupin.config import Settings
from lupin.core.llm.base import LLMTextDelta
from lupin.main import create_app
from lupin.storage.database import create_engine
from lupin.storage.models import Base
from tests.conftest import OWNER_TELEGRAM_ID, FakeLLM
from tests.test_telegram import FakeBotAPI, update

SECRET = "s3cret-token"


async def _create_tables(url: str) -> None:
    engine = create_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture
def db_url(tmp_path) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'app.db'}"
    asyncio.run(_create_tables(url))
    return url


def settings(db_url: str, **overrides) -> Settings:
    values = {
        "database_url": db_url,
        "openai_api_key": "sk-test",
        "telegram_mode": "webhook",
        "telegram_bot_token": "TOKEN",
        "telegram_owner_user_id": int(OWNER_TELEGRAM_ID),
        "telegram_webhook_secret": SECRET,
        "public_base_url": "https://lupin.example.com",
        "debug_api_enabled": True,
    }
    return Settings(_env_file=None, **{**values, **overrides})


def wait_for(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.01)


def test_webhook_mode_end_to_end(db_url):
    api = FakeBotAPI()
    app = create_app(
        settings(db_url),
        llm=FakeLLM([LLMTextDelta("Hello!")]),
        tools=[],
        telegram_client=api.client(),
    )

    with TestClient(app) as client:
        wait_for(lambda: any(m == "setWebhook" for m, _ in api.calls))
        set_webhook = next(p for m, p in api.calls if m == "setWebhook")
        assert set_webhook["url"] == "https://lupin.example.com/channels/telegram/webhook"
        assert set_webhook["secret_token"] == SECRET

        rejected = client.post(
            "/channels/telegram/webhook",
            json=update("hi"),
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        accepted = client.post(
            "/channels/telegram/webhook",
            json=update("hi"),
            headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
        )

        assert rejected.status_code == 401
        assert accepted.status_code == 200
        assert api.sent_texts() == ["Hello!"]
        assert client.get("/healthz").json() == {"status": "ok"}


def test_debug_chat_endpoint(db_url):
    app = create_app(
        settings(db_url, telegram_mode="disabled"),
        llm=FakeLLM([LLMTextDelta("Pong")]),
        tools=[],
    )

    with TestClient(app) as client:
        response = client.post("/debug/chat", json={"text": "ping"})

    assert response.status_code == 200
    assert response.json()["reply"] == "Pong"


def test_debug_endpoint_absent_unless_enabled(db_url):
    app = create_app(
        settings(db_url, telegram_mode="disabled", debug_api_enabled=False), llm=FakeLLM()
    )

    with TestClient(app) as client:
        assert client.post("/debug/chat", json={"text": "ping"}).status_code == 404


def test_webhook_mode_requires_a_secret(db_url):
    with pytest.raises(ValueError, match="TELEGRAM_WEBHOOK_SECRET"):
        settings(db_url, telegram_webhook_secret=None)


def test_blank_env_values_count_as_unset(db_url):
    config = settings(db_url, telegram_mode="disabled", tavily_api_key="", public_base_url=" ")

    assert config.tavily_api_key is None
    assert config.public_base_url is None
