
import inspect
from typing import Any


class ToolRegistry:
    """Allow the agent to invoke only approved bank lookup methods."""

    ALLOWED_TOOLS = {
        "get_account",
        "get_balance",
        "get_bank_status",
    }

    REQUIRED_ARGUMENTS = {
        "get_account": {"account_number"},
        "get_balance": {"account_number"},
        "get_bank_status": {"bic_code"},
    }

    def __init__(self, bank_client: Any):
        self.bank_client = bank_client

    def descriptions(self) -> list[dict]:
        return [
            {
                "name": "get_account",
                "description": "Look up beneficiary account details.",
                "arguments": ["account_number"],
            },
            {
                "name": "get_balance",
                "description": "Look up an account balance.",
                "arguments": ["account_number"],
            },
            {
                "name": "get_bank_status",
                "description": "Look up bank availability using its BIC.",
                "arguments": ["bic_code"],
            },
        ]

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:

        # Never allow the LLM to select arbitrary tools or URLs.
        if tool_name not in self.ALLOWED_TOOLS:
            return {
                "ok": False,
                "error": "TOOL_NOT_ALLOWED",
            }

        if not isinstance(arguments, dict):
            return {
                "ok": False,
                "error": "INVALID_TOOL_ARGUMENTS",
            }

        required = self.REQUIRED_ARGUMENTS[tool_name]

        if set(arguments.keys()) != required:
            return {
                "ok": False,
                "error": "INVALID_TOOL_ARGUMENTS",
            }

        method = getattr(self.bank_client, tool_name, None)

        if not callable(method):
            return {
                "ok": False,
                "error": "TOOL_UNAVAILABLE",
            }

        try:
            result = method(**arguments)

            if inspect.isawaitable(result):
                result = await result

            if hasattr(result, "model_dump"):
                result = result.model_dump(mode="json")
            elif hasattr(result, "dict"):
                result = result.dict()

            if isinstance(result, dict):
                return result

            return {
                "ok": True,
                "data": result,
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": "BANK_TOOL_ERROR",
                "detail": type(exc).__name__,
            }
