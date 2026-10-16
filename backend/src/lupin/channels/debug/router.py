"""HTTP channel for local testing with curl or Bruno. Enabled with DEBUG_API_ENABLED."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from lupin.assistant import Assistant
from lupin.domain.messages import Channel, InboundMessage

DEBUG_SENDER_ID = "owner"

router = APIRouter(prefix="/debug", tags=["debug"])


class ChatRequest(BaseModel):
    text: str
    chat_id: str = "default"


class ToolCallView(BaseModel):
    name: str
    output: str
    is_error: bool


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[ToolCallView]
    usage: dict[str, Any]


@router.post("/chat")
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    assistant: Assistant | None = getattr(request.app.state, "debug_assistant", None)
    if assistant is None:
        raise HTTPException(status_code=404)
    reply = await assistant.handle(
        InboundMessage(
            channel=Channel.DEBUG,
            sender_id=DEBUG_SENDER_ID,
            chat_id=body.chat_id,
            text=body.text,
            event_id=f"debug:{uuid.uuid4()}",
        )
    )
    if reply is None:
        raise HTTPException(status_code=403)
    return ChatResponse(
        reply=reply.text,
        tool_calls=[
            ToolCallView(name=c.name, output=c.output, is_error=c.is_error)
            for c in reply.tool_calls
        ],
        usage={
            "input_tokens": reply.usage.input_tokens,
            "output_tokens": reply.usage.output_tokens,
        },
    )
