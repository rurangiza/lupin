import asyncio

from pydantic import BaseModel

from lupin.core.agent import Agent
from lupin.core.events import Done, TextDelta, ToolCallFinished, ToolCallStarted, Usage
from lupin.core.llm.base import LLMTextDelta, LLMToolCalls, LLMUsage
from lupin.core.tools.base import Tool, ToolRegistry
from lupin.domain.messages import ChatMessage, Role, ToolCall
from tests.conftest import FakeLLM


class EchoArgs(BaseModel):
    text: str


class Echo(Tool[EchoArgs]):
    name = "echo"
    description = "Echo the text back"
    arguments = EchoArgs

    async def run(self, args: EchoArgs) -> str:
        return f"echo: {args.text}"


class Slow(Tool[EchoArgs]):
    name = "slow"
    description = "Never finishes in time"
    arguments = EchoArgs

    async def run(self, args: EchoArgs) -> str:
        await asyncio.sleep(10)
        return "too late"


async def collect(agent: Agent, text: str = "hi"):
    return [e async for e in agent.respond("system", [], ChatMessage(Role.USER, text))]


def agent_with(llm: FakeLLM, *tools: Tool, max_rounds: int = 3) -> Agent:
    return Agent(llm, ToolRegistry(list(tools), timeout_seconds=0.05), max_tool_rounds=max_rounds)


async def test_plain_reply_streams_text_then_done():
    llm = FakeLLM([LLMTextDelta("Hel"), LLMTextDelta("lo"), LLMUsage(Usage(10, 2))])

    events = await collect(agent_with(llm))

    assert events[:2] == [TextDelta("Hel"), TextDelta("lo")]
    done = events[-1]
    assert isinstance(done, Done)
    assert done.text == "Hello"
    assert done.usage == Usage(10, 2)
    assert [m.role for m in done.new_messages] == [Role.USER, Role.ASSISTANT]


async def test_tool_call_result_is_fed_back_to_the_model():
    call = ToolCall("c1", "echo", {"text": "ping"})
    llm = FakeLLM(
        [LLMToolCalls([call]), LLMUsage(Usage(5, 1))],
        [LLMTextDelta("Got it"), LLMUsage(Usage(8, 2))],
    )

    events = await collect(agent_with(llm, Echo()))

    assert ToolCallStarted("c1", "echo", {"text": "ping"}) in events
    assert ToolCallFinished("c1", "echo", "echo: ping", False) in events
    second_prompt = llm.prompts[1]
    assert second_prompt[-1] == ChatMessage(Role.TOOL, "echo: ping", tool_call_id="c1")
    done = events[-1]
    assert done.text == "Got it"
    assert done.usage == Usage(13, 3)
    assert [m.role for m in done.new_messages] == [
        Role.USER,
        Role.ASSISTANT,
        Role.TOOL,
        Role.ASSISTANT,
    ]


async def test_tool_failures_are_reported_to_the_model_not_raised():
    llm = FakeLLM(
        [
            LLMToolCalls(
                [
                    ToolCall("a", "missing", {}),
                    ToolCall("b", "echo", {"wrong": 1}),
                    ToolCall("c", "slow", {"text": "x"}),
                ]
            )
        ],
        [LLMTextDelta("Sorry")],
    )

    events = await collect(agent_with(llm, Echo(), Slow()))

    finished = [e for e in events if isinstance(e, ToolCallFinished)]
    assert all(e.is_error for e in finished)
    assert "Unknown tool" in finished[0].output
    assert "Invalid arguments" in finished[1].output
    assert "timed out" in finished[2].output
    assert events[-1].text == "Sorry"


async def test_last_round_withholds_tools_so_the_model_must_answer():
    loop_call = [LLMToolCalls([ToolCall("x", "echo", {"text": "again"})])]
    llm = FakeLLM(loop_call, loop_call, [LLMTextDelta("Stopping here")])

    events = await collect(agent_with(llm, Echo(), max_rounds=2))

    assert [len(tools) for tools in llm.offered_tools] == [1, 1, 0]
    assert events[-1].text == "Stopping here"
