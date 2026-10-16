from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from lupin.assistant import Assistant
from lupin.core.agent import Agent
from lupin.core.llm.base import LLMEvent, ToolSpec
from lupin.core.tools.base import Tool, ToolRegistry
from lupin.domain.messages import Channel, ChatMessage
from lupin.storage import repositories as repo
from lupin.storage.database import create_engine, create_session_factory
from lupin.storage.models import Base

OWNER_TELEGRAM_ID = "1001"


class FakeLLM:
    """Replays scripted responses and records every prompt it receives."""

    model = "fake-model"

    def __init__(self, *responses: list[LLMEvent]) -> None:
        self._responses = list(responses)
        self.prompts: list[list[ChatMessage]] = []
        self.offered_tools: list[list[ToolSpec]] = []

    async def stream(
        self, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> AsyncIterator[LLMEvent]:
        self.prompts.append(list(messages))
        self.offered_tools.append(list(tools))
        if not self._responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        for event in self._responses.pop(0):
            yield event


@pytest.fixture
def database_url(tmp_path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
async def sessions(database_url) -> AsyncIterator[async_sessionmaker]:
    engine = create_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def owner_id(sessions):
    async with sessions() as session:
        return await repo.ensure_owner(session, "Arsene", [(Channel.TELEGRAM, OWNER_TELEGRAM_ID)])


def make_assistant(sessions, llm: FakeLLM, tools: list[Tool] | None = None, **kwargs) -> Assistant:
    agent = Agent(llm, ToolRegistry(tools or [], timeout_seconds=1.0), max_tool_rounds=3)
    return Assistant(
        agent,
        sessions,
        owner_name="Arsene",
        timezone="Europe/Brussels",
        history_limit=kwargs.get("history_limit", 30),
    )
