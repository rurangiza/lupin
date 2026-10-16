import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel, ValidationError

from lupin.core.llm.base import ToolSpec
from lupin.domain.messages import ToolCall

logger = logging.getLogger(__name__)


class Tool[ArgsT: BaseModel](ABC):
    """A capability the agent can call.

    Subclasses declare their arguments as a pydantic model, which doubles as
    the JSON schema sent to the model.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    arguments: ClassVar[type[BaseModel]]

    @abstractmethod
    async def run(self, args: ArgsT) -> str: ...

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.arguments.model_json_schema(),
        )


@dataclass(frozen=True)
class ToolResult:
    output: str
    is_error: bool = False


class ToolRegistry:
    def __init__(self, tools: list[Tool], timeout_seconds: float) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._timeout = timeout_seconds

    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools.values()]

    async def execute(self, call: ToolCall) -> ToolResult:
        """Run a tool call. Failures are returned to the model, never raised."""
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(f"Unknown tool: {call.name}", is_error=True)
        try:
            args = tool.arguments.model_validate(call.arguments)
        except ValidationError as e:
            return ToolResult(f"Invalid arguments: {e}", is_error=True)
        try:
            output = await asyncio.wait_for(tool.run(args), timeout=self._timeout)
        except TimeoutError:
            return ToolResult(f"{call.name} timed out after {self._timeout}s", is_error=True)
        except Exception as e:
            logger.exception("Tool %s failed", call.name)
            return ToolResult(f"{call.name} failed: {e}", is_error=True)
        return ToolResult(output)
