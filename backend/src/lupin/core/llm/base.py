from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from lupin.core.events import Usage
from lupin.domain.messages import ChatMessage, ToolCall


@dataclass(frozen=True)
class ToolSpec:
    """A tool described independently of any provider."""

    name: str
    description: str
    parameters: dict[str, Any]
    """JSON schema of the arguments."""


@dataclass(frozen=True)
class LLMTextDelta:
    text: str


@dataclass(frozen=True)
class LLMToolCalls:
    calls: list[ToolCall]


@dataclass(frozen=True)
class LLMUsage:
    usage: Usage


LLMEvent = LLMTextDelta | LLMToolCalls | LLMUsage


class LLMProvider(Protocol):
    """Streams one model response. Implementations keep no per-request state."""

    model: str

    def stream(
        self, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> AsyncIterator[LLMEvent]: ...
