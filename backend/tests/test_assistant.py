from lupin.assistant import FAILURE_REPLY, NEW_CONVERSATION_REPLY
from lupin.core.events import Usage
from lupin.core.llm.base import LLMTextDelta, LLMToolCalls, LLMUsage
from lupin.domain.messages import Channel, InboundMessage, Role, ToolCall
from tests.conftest import OWNER_TELEGRAM_ID, FakeLLM, make_assistant
from tests.test_agent import Echo


def inbound(text: str, event_id: str, sender: str = OWNER_TELEGRAM_ID) -> InboundMessage:
    return InboundMessage(
        channel=Channel.TELEGRAM, sender_id=sender, chat_id="chat", text=text, event_id=event_id
    )


async def test_unknown_sender_is_ignored(sessions, owner_id):
    llm = FakeLLM()
    assistant = make_assistant(sessions, llm)

    assert await assistant.handle(inbound("hi", "e1", sender="999")) is None
    assert llm.prompts == []


async def test_duplicate_delivery_is_answered_once(sessions, owner_id):
    assistant = make_assistant(sessions, FakeLLM([LLMTextDelta("Hi")]))

    first = await assistant.handle(inbound("hello", "e1"))
    second = await assistant.handle(inbound("hello", "e1"))

    assert first.text == "Hi"
    assert second is None


async def test_history_includes_tool_exchange_from_previous_turns(sessions, owner_id):
    llm = FakeLLM(
        [LLMToolCalls([ToolCall("c1", "echo", {"text": "x"})])],
        [LLMTextDelta("First answer"), LLMUsage(Usage(3, 4))],
        [LLMTextDelta("Second answer")],
    )
    assistant = make_assistant(sessions, llm, tools=[Echo()])

    await assistant.handle(inbound("first", "e1"))
    reply = await assistant.handle(inbound("second", "e2"))

    assert reply.text == "Second answer"
    last_prompt = llm.prompts[-1]
    assert [m.role for m in last_prompt] == [
        Role.SYSTEM,
        Role.USER,
        Role.ASSISTANT,
        Role.TOOL,
        Role.ASSISTANT,
        Role.USER,
    ]
    assert last_prompt[3].tool_call_id == "c1"
    assert last_prompt[-1].content == "second"


async def test_history_window_never_starts_mid_tool_exchange(sessions, owner_id):
    llm = FakeLLM(
        [LLMToolCalls([ToolCall("c1", "echo", {"text": "x"})])],
        [LLMTextDelta("First answer")],
        [LLMTextDelta("Second answer")],
    )
    # 4 messages from turn one; a window of 3 would start at the tool call.
    assistant = make_assistant(sessions, llm, tools=[Echo()], history_limit=3)

    await assistant.handle(inbound("first", "e1"))
    await assistant.handle(inbound("second", "e2"))

    assert [m.role for m in llm.prompts[-1]] == [Role.SYSTEM, Role.USER]


async def test_new_command_starts_a_fresh_conversation(sessions, owner_id):
    llm = FakeLLM([LLMTextDelta("One")], [LLMTextDelta("Two")])
    assistant = make_assistant(sessions, llm)

    await assistant.handle(inbound("remember this", "e1"))
    reset = await assistant.handle(inbound("/new", "e2"))
    await assistant.handle(inbound("what did I say?", "e3"))

    assert reset.text == NEW_CONVERSATION_REPLY
    assert [m.content for m in llm.prompts[-1][1:]] == ["what did I say?"]


async def test_model_failure_returns_an_apology(sessions, owner_id):
    assistant = make_assistant(sessions, FakeLLM())  # no scripted response: raises

    reply = await assistant.handle(inbound("hi", "e1"))

    assert reply.text == FAILURE_REPLY
