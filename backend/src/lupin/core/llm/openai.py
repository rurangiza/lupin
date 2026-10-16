import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from lupin.core.events import Usage
from lupin.core.llm.base import LLMEvent, LLMTextDelta, LLMToolCalls, LLMUsage, ToolSpec
from lupin.domain.messages import ChatMessage, Role, ToolCall

logger = logging.getLogger(__name__)


class OpenAIProvider:
    def __init__(self, api_key: str, model: str, client: AsyncOpenAI | None = None) -> None:
        self.model = model
        self._client = client or AsyncOpenAI(api_key=api_key)

    async def stream(
        self, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> AsyncIterator[LLMEvent]:
        kwargs: dict[str, Any] = {}
        if tools:
            kwargs["tools"] = [_to_openai_tool(tool) for tool in tools]

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[_to_openai_message(m) for m in messages],
            stream=True,
            stream_options={"include_usage": True},
            **kwargs,
        )

        # Tool call arguments arrive in fragments, keyed by their index.
        pending: dict[int, dict[str, str]] = {}
        async for chunk in response:
            if chunk.usage is not None:
                yield LLMUsage(Usage(chunk.usage.prompt_tokens, chunk.usage.completion_tokens))
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield LLMTextDelta(delta.content)
            for fragment in delta.tool_calls or []:
                call = pending.setdefault(fragment.index, {"id": "", "name": "", "arguments": ""})
                if fragment.id:
                    call["id"] = fragment.id
                if fragment.function and fragment.function.name:
                    call["name"] = fragment.function.name
                if fragment.function and fragment.function.arguments:
                    call["arguments"] += fragment.function.arguments

        if pending:
            yield LLMToolCalls([_parse_tool_call(pending[i]) for i in sorted(pending)])


def _parse_tool_call(raw: dict[str, str]) -> ToolCall:
    try:
        arguments = json.loads(raw["arguments"] or "{}")
    except json.JSONDecodeError:
        logger.warning("Model sent invalid JSON arguments for %s", raw["name"])
        arguments = {}
    return ToolCall(id=raw["id"], name=raw["name"], arguments=arguments)


def _to_openai_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _to_openai_message(message: ChatMessage) -> dict[str, Any]:
    match message.role:
        case Role.TOOL:
            return {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": message.content or "",
            }
        case Role.ASSISTANT if message.tool_calls:
            return {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                    }
                    for call in message.tool_calls
                ],
            }
        case _:
            return {"role": message.role.value, "content": message.content or ""}
