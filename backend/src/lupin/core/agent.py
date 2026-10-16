from collections.abc import AsyncIterator

from lupin.core.events import (
    AgentEvent,
    Done,
    TextDelta,
    ToolCallFinished,
    ToolCallStarted,
    Usage,
)
from lupin.core.llm.base import LLMProvider, LLMTextDelta, LLMToolCalls, LLMUsage
from lupin.core.tools.base import ToolRegistry
from lupin.domain.messages import ChatMessage, Role

TOOL_LIMIT_NOTICE = (
    "Tool limit reached for this turn. Answer with what you have, "
    "and say what you could not finish."
)


class Agent:
    """Runs the model/tool loop for one turn. Holds no per-turn state."""

    def __init__(self, llm: LLMProvider, tools: ToolRegistry, max_tool_rounds: int) -> None:
        self._llm = llm
        self._tools = tools
        self._max_tool_rounds = max_tool_rounds

    async def respond(
        self, system_prompt: str, history: list[ChatMessage], message: ChatMessage
    ) -> AsyncIterator[AgentEvent]:
        new_messages = [message]
        usage = Usage()
        specs = self._tools.specs()

        for round_number in range(self._max_tool_rounds + 1):
            # On the last round, withhold tools so the model has to answer.
            offer_tools = specs if round_number < self._max_tool_rounds else []
            prompt = [ChatMessage(Role.SYSTEM, system_prompt), *history, *new_messages]
            if not offer_tools and round_number > 0:
                prompt.append(ChatMessage(Role.SYSTEM, TOOL_LIMIT_NOTICE))

            text_parts: list[str] = []
            tool_calls = []
            async for event in self._llm.stream(prompt, offer_tools):
                match event:
                    case LLMTextDelta(text):
                        text_parts.append(text)
                        yield TextDelta(text)
                    case LLMToolCalls(calls):
                        tool_calls = calls
                    case LLMUsage(round_usage):
                        usage += round_usage

            text = "".join(text_parts)
            new_messages.append(
                ChatMessage(Role.ASSISTANT, content=text or None, tool_calls=tool_calls)
            )
            if not tool_calls:
                yield Done(text=text, new_messages=new_messages, usage=usage, model=self._llm.model)
                return

            for call in tool_calls:
                yield ToolCallStarted(call.id, call.name, call.arguments)
                result = await self._tools.execute(call)
                yield ToolCallFinished(call.id, call.name, result.output, result.is_error)
                new_messages.append(
                    ChatMessage(Role.TOOL, content=result.output, tool_call_id=call.id)
                )

        raise AssertionError("unreachable: the last round offers no tools")
