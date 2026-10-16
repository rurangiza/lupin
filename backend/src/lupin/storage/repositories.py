import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lupin.core.events import Usage
from lupin.domain.messages import Channel, ChatMessage, Role, ToolCall
from lupin.storage.models import ChannelIdentity, Conversation, Message, ProcessedEvent, User


async def resolve_user(
    session: AsyncSession, channel: Channel, external_id: str
) -> uuid.UUID | None:
    return await session.scalar(
        select(ChannelIdentity.user_id).where(
            ChannelIdentity.channel == channel.value,
            ChannelIdentity.external_id == external_id,
        )
    )


async def ensure_owner(
    session: AsyncSession, display_name: str, identities: list[tuple[Channel, str]]
) -> uuid.UUID:
    """Create the owner and their channel identities if missing. Safe to run on every start."""
    user_id = None
    for channel, external_id in identities:
        user_id = user_id or await resolve_user(session, channel, external_id)
    if user_id is None:
        user = User(display_name=display_name)
        session.add(user)
        await session.flush()
        user_id = user.id

    for channel, external_id in identities:
        if await resolve_user(session, channel, external_id) is None:
            session.add(
                ChannelIdentity(user_id=user_id, channel=channel.value, external_id=external_id)
            )
    await session.commit()
    return user_id


async def claim_event(session: AsyncSession, event_id: str) -> bool:
    """Record an inbound event. Returns False if it was already handled."""
    session.add(ProcessedEvent(event_id=event_id))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return False
    return True


async def get_or_create_conversation(
    session: AsyncSession, user_id: uuid.UUID, channel: Channel, chat_id: str
) -> uuid.UUID:
    conversation_id = await session.scalar(
        select(Conversation.id)
        .where(
            Conversation.user_id == user_id,
            Conversation.channel == channel.value,
            Conversation.chat_id == chat_id,
            Conversation.closed_at.is_(None),
        )
        .order_by(Conversation.started_at.desc())
        .limit(1)
    )
    if conversation_id is not None:
        return conversation_id
    conversation = Conversation(user_id=user_id, channel=channel.value, chat_id=chat_id)
    session.add(conversation)
    await session.commit()
    return conversation.id


async def close_conversation(
    session: AsyncSession, user_id: uuid.UUID, channel: Channel, chat_id: str
) -> None:
    await session.execute(
        update(Conversation)
        .where(
            Conversation.user_id == user_id,
            Conversation.channel == channel.value,
            Conversation.chat_id == chat_id,
            Conversation.closed_at.is_(None),
        )
        .values(closed_at=datetime.now(UTC))
    )
    await session.commit()


async def load_history(
    session: AsyncSession, conversation_id: uuid.UUID, limit: int
) -> list[ChatMessage]:
    rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.seq.desc())
            .limit(limit)
        )
    ).all()
    messages = [_to_chat_message(row) for row in reversed(rows)]
    # The window can cut a tool exchange in half, which the model rejects.
    # Start at the first user message so every tool result keeps its call.
    while messages and messages[0].role is not Role.USER:
        messages.pop(0)
    return messages


async def append_messages(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    messages: list[ChatMessage],
    usage: Usage,
    model: str,
) -> None:
    last_seq = await session.scalar(
        select(func.max(Message.seq)).where(Message.conversation_id == conversation_id)
    )
    next_seq = (last_seq or 0) + 1
    final_assistant = max(
        (i for i, m in enumerate(messages) if m.role is Role.ASSISTANT), default=None
    )
    for i, message in enumerate(messages):
        # Turn-level usage is stored on the final assistant message.
        is_final = i == final_assistant
        session.add(
            Message(
                conversation_id=conversation_id,
                seq=next_seq + i,
                role=message.role.value,
                content=message.content,
                tool_calls=[
                    {"id": c.id, "name": c.name, "arguments": c.arguments}
                    for c in message.tool_calls
                ]
                or None,
                tool_call_id=message.tool_call_id,
                model=model if message.role is Role.ASSISTANT else None,
                input_tokens=usage.input_tokens if is_final else None,
                output_tokens=usage.output_tokens if is_final else None,
            )
        )
    await session.commit()


def _to_chat_message(row: Message) -> ChatMessage:
    return ChatMessage(
        role=Role(row.role),
        content=row.content,
        tool_calls=[ToolCall(**call) for call in row.tool_calls or []],
        tool_call_id=row.tool_call_id,
    )
