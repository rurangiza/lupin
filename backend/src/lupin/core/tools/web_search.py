from typing import Literal

from pydantic import BaseModel, Field
from tavily import AsyncTavilyClient

from lupin.core.tools.base import Tool


class WebSearchArgs(BaseModel):
    query: str = Field(
        description="A natural language search string that clearly describes what the "
        "user wants to know, specific enough for a search engine to return relevant results."
    )
    topic: Literal["general", "news", "finance"] = Field(
        default="general",
        description="'news' for current events, 'finance' for markets and money, "
        "'general' for everything else.",
    )


class WebSearch(Tool[WebSearchArgs]):
    name = "web_search"
    description = (
        "Search the web for up-to-date information. Use it for recent events, facts you are "
        "unsure about, or anything that may have changed since your training."
    )
    arguments = WebSearchArgs

    def __init__(self, api_key: str, max_results: int = 5) -> None:
        self._client = AsyncTavilyClient(api_key=api_key)
        self._max_results = max_results

    async def run(self, args: WebSearchArgs) -> str:
        response = await self._client.search(
            query=args.query,
            topic=args.topic,
            max_results=self._max_results,
            include_answer="basic",
        )
        results = response.get("results", [])
        if not results:
            return f"No results found for: {args.query}"
        sections = [f"{r['title']} ({r['url']})\n{r['content']}" for r in results]
        if answer := response.get("answer"):
            sections.insert(0, f"Summary: {answer}")
        return "\n\n---\n\n".join(sections)
