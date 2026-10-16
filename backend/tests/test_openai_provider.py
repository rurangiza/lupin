"""Checks the OpenAI adapter against recorded-shape streaming responses, offline."""

import json

import httpx
from openai import AsyncOpenAI

from lupin.core.events import Usage
from lupin.core.llm.base import LLMTextDelta, LLMToolCalls, LLMUsage, ToolSpec
from lupin.core.llm.openai import OpenAIProvider
from lupin.domain.messages import ChatMessage, Role, ToolCall


def sse(*chunks: dict) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks] + ["data: [DONE]\n\n"]
    return "".join(lines).encode()


def chunk(delta: dict | None = None, usage: dict | None = None) -> dict:
    return {
        "id": "x",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "m",
        "choices": [] if delta is None else [{"index": 0, "delta": delta, "finish_reason": None}],
        "usage": usage,
    }


def provider_returning(body: bytes, captured: list) -> OpenAIProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    client = AsyncOpenAI(
        api_key="sk-test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    return OpenAIProvider("sk-test", "m", client=client)


async def test_streamed_tool_call_fragments_are_reassembled():
    body = sse(
        chunk({"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "web_search"}}]}),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"query":'}}]}),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": ' "belgium"}'}}]}),
        chunk(usage={"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}),
    )
    captured: list = []
    provider = provider_returning(body, captured)
    spec = ToolSpec("web_search", "Search", {"type": "object", "properties": {}})

    events = [e async for e in provider.stream([ChatMessage(Role.USER, "hi")], [spec])]

    assert LLMUsage(Usage(12, 5)) in events
    assert events[-1] == LLMToolCalls([ToolCall("c1", "web_search", {"query": "belgium"})])
    assert captured[0]["tools"][0]["function"]["name"] == "web_search"
    assert captured[0]["stream"] is True


async def test_text_deltas_and_tool_history_serialisation():
    body = sse(chunk({"content": "Hel"}), chunk({"content": "lo"}))
    captured: list = []
    provider = provider_returning(body, captured)
    history = [
        ChatMessage(Role.USER, "search"),
        ChatMessage(Role.ASSISTANT, tool_calls=[ToolCall("c1", "web_search", {"query": "q"})]),
        ChatMessage(Role.TOOL, "results", tool_call_id="c1"),
    ]

    events = [e async for e in provider.stream(history, [])]

    assert events == [LLMTextDelta("Hel"), LLMTextDelta("lo")]
    sent = captured[0]["messages"]
    assert sent[1]["tool_calls"][0]["function"] == {
        "name": "web_search",
        "arguments": '{"query": "q"}',
    }
    assert sent[2] == {"role": "tool", "tool_call_id": "c1", "content": "results"}
    assert "tools" not in captured[0]
