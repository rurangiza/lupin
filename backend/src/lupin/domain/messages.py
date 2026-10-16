"""Channel-agnostic message types.

Every channel adapter converts its own payloads into these types, so the
assistant never needs to know which channel a message came from.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Channel(StrEnum):
    TELEGRAM = "telegram"
    DEBUG = "debug"


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatMessage:
    """One turn in a conversation, in a provider-neutral shape."""

    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass(frozen=True)
class Capabilities:
    """What the channel can render, so replies can be shaped for it."""

    markdown: bool = True
    max_reply_chars: int | None = None
    voice: bool = False


@dataclass(frozen=True)
class InboundMessage:
    channel: Channel
    sender_id: str
    """The sender's id on the channel (Telegram user id, phone number, ...)."""
    chat_id: str
    """Where to reply on the channel. Also scopes the conversation."""
    text: str
    event_id: str
    """Unique per delivery, used to drop retries and duplicates."""
    capabilities: Capabilities = field(default_factory=Capabilities)
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class OutboundMessage:
    channel: Channel
    chat_id: str
    text: str
