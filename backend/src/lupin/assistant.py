import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import async_sessionmaker

from lupin.core.agent import Agent
from lupin.core.events import Done, ToolCallFinished, Usage
from lupin.core.prompts import build_system_prompt
from lupin.domain.messages import ChatMessage, InboundMessage, Role
from lupin.storage import repositories as repo

logger = logging.getLogger(__name__)

NEW_CONVERSATION_COMMANDS = {"/new", "/start"}
NEW_CONVERSATION_REPLY = "Started a new conversation. What can I do for you?"
FAILURE_REPLY = "Sorry, something went wrong on my side. Please try again."


@dataclass(frozen=True)
class Reply:
    text: str
    tool_calls: list[ToolCallFinished] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


class Assistant:
    """Handles one inbound message from any channel, end to end."""

    def __init__(
        self,
        agent: Agent,
        sessions: async_sessionmaker,
        owner_name: str,
        timezone: str,
        history_limit: int,
    ) -> None:
        self._agent = agent
        self._sessions = sessions
        self._owner_name = owner_name
        self._timezone = timezone
        self._history_limit = history_limit
        # One turn at a time per chat, so two quick messages don't interleave
        # their history. In-process only: multiple replicas will need a DB lock.
        self._locks: defaultdict[tuple[str, str], asyncio.Lock] = defaultdict(asyncio.Lock)

    async def is_known(self, inbound: InboundMessage) -> bool:
        async with self._sessions() as session:
            user_id = await repo.resolve_user(session, inbound.channel, inbound.sender_id)
        if user_id is None:
            logger.warning(
                "Ignoring message from unknown sender %s on %s", inbound.sender_id, inbound.channel
            )
        return user_id is not None

    async def handle(self, inbound: InboundMessage) -> Reply | None:
        """Returns None when the message must be ignored (unknown sender, duplicate)."""
        async with self._sessions() as session:
            user_id = await repo.resolve_user(session, inbound.channel, inbound.sender_id)
            if user_id is None:
                logger.warning(
                    "Dropping message from unknown sender %s on %s",
                    inbound.sender_id,
                    inbound.channel,
                )
                return None
            if not await repo.claim_event(session, inbound.event_id):
                logger.info("Skipping duplicate event %s", inbound.event_id)
                return None

        async with self._locks[(inbound.channel.value, inbound.chat_id)]:
            if inbound.text.strip().lower() in NEW_CONVERSATION_COMMANDS:
                async with self._sessions() as session:
                    await repo.close_conversation(
                        session, user_id, inbound.channel, inbound.chat_id
                    )
                return Reply(NEW_CONVERSATION_REPLY)

            try:
                return await self._run_turn(user_id, inbound)
            except Exception:
                logger.exception("Turn failed for event %s", inbound.event_id)
                return Reply(FAILURE_REPLY)

    async def _run_turn(self, user_id, inbound: InboundMessage) -> Reply:
        async with self._sessions() as session:
            conversation_id = await repo.get_or_create_conversation(
                session, user_id, inbound.channel, inbound.chat_id
            )
            history = await repo.load_history(session, conversation_id, self._history_limit)

        system_prompt = build_system_prompt(self._owner_name, self._timezone, inbound.capabilities)
        tool_calls: list[ToolCallFinished] = []
        done: Done | None = None
        async for event in self._agent.respond(
            system_prompt, history, ChatMessage(Role.USER, inbound.text)
        ):
            match event:
                case ToolCallFinished():
                    tool_calls.append(event)
                case Done():
                    done = event
        assert done is not None

        async with self._sessions() as session:
            await repo.append_messages(
                session, conversation_id, done.new_messages, done.usage, done.model
            )
        return Reply(done.text, tool_calls, done.usage)
