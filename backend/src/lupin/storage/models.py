import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True), dict[str, Any]: JSON}


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=_now)

    identities: Mapped[list["ChannelIdentity"]] = relationship(back_populates="user")


class ChannelIdentity(Base):
    """Maps a sender on a channel to a user. A missing row means the sender is unknown."""

    __tablename__ = "channel_identities"
    __table_args__ = (UniqueConstraint("channel", "external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=_now)

    user: Mapped[User] = relationship(back_populates="identities")


class Conversation(Base):
    """A thread on one channel. Closing it starts a fresh one on the next message."""

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_lookup", "user_id", "channel", "chat_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(32))
    chat_id: Mapped[str] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(default=_now)
    closed_at: Mapped[datetime | None]


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation", "conversation_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    seq: Mapped[int]
    """Position in the conversation. Timestamps can tie within one turn."""
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    tool_call_id: Mapped[str | None] = mapped_column(String(200))
    model: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(default=_now)


class ProcessedEvent(Base):
    """Inbound deliveries already handled, so channel retries are not answered twice."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
