from datetime import datetime
from zoneinfo import ZoneInfo

from lupin.domain.messages import Capabilities


def build_system_prompt(owner_name: str, timezone: str, capabilities: Capabilities) -> str:
    now = datetime.now(ZoneInfo(timezone))
    lines = [
        f"You are Lupin, the personal assistant of {owner_name}.",
        "Be direct and concise. Ask a short question when a request is ambiguous.",
        "When you use web search, mention your sources.",
        f"Current date and time: {now:%A %d %B %Y, %H:%M} ({timezone}).",
    ]
    if capabilities.voice:
        lines.append(
            "You are speaking on a phone call. Answer in short spoken sentences, "
            "with no lists, markdown or URLs."
        )
    elif capabilities.markdown:
        lines.append("You may use light markdown: bold, italics, inline code, code blocks, links.")
    else:
        lines.append("Reply in plain text, without markdown.")
    return "\n".join(lines)
