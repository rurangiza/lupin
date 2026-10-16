from typing import Protocol

from lupin.domain.messages import Channel, OutboundMessage


class TextChannel(Protocol):
    """A channel that can deliver text. Each adapter also owns its inbound transport
    (webhook route, poller, websocket) and converts payloads to InboundMessage."""

    channel: Channel

    async def send(self, message: OutboundMessage) -> None: ...
