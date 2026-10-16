"""Events emitted while the agent works on a reply.

Text channels collect them into one message. A voice channel can forward
text deltas to speech synthesis as they arrive.
"""

from dataclasses import dataclass, field
from typing import Any

from lupin.domain.messages import ChatMessage


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
        )


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCallStarted:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolCallFinished:
    call_id: str
    name: str
    output: str
    is_error: bool


@dataclass(frozen=True)
class Done:
    text: str
    new_messages: list[ChatMessage] = field(default_factory=list)
    """Messages produced during this turn, in order, ready to be persisted."""
    usage: Usage = field(default_factory=Usage)
    model: str = ""


AgentEvent = TextDelta | ToolCallStarted | ToolCallFinished | Done
