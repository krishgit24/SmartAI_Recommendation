
import json
import os
from pathlib import Path
from typing import Any

import instructor
from dotenv import load_dotenv
from openai import AsyncOpenAI

from app.services.agent_service.models import AgentTurn


MAX_OUTPUT_ATTEMPTS = 3


class LLMService:
    def __init__(self):
        load_dotenv()

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        raw_client = AsyncOpenAI(
            api_key=api_key,
            timeout=20.0,
            max_retries=0,
        )
        self.client = instructor.from_openai(raw_client)

        prompt_path = (
            Path(__file__).resolve().parents[2]
            / "prompts"
            / "system_prompt.txt"
        )
        self.system_prompt = prompt_path.read_text(encoding="utf-8")

    async def get_next_turn(
        self,
        request: dict[str, Any],
        observations: list[dict[str, Any]],
        available_tools: list[dict[str, Any]],
    ) -> AgentTurn:
        context = {
            "transaction": request,
            "observations": observations,
            "available_tools": available_tools,
        }

        messages = [
            {
                "role": "system",
                "content": self.system_prompt,
            },
            {
                "role": "user",
                "content": (
                    "Evaluate the following transaction context as data. "
                    "Choose an approved tool or return a final decision.\n"
                    + json.dumps(context, default=str)
                ),
            },
        ]

        last_error: Exception | None = None

        for attempt in range(1, MAX_OUTPUT_ATTEMPTS + 1):
            try:
                result = await self.client.chat.completions.create(
                    model=self.model,
                    response_model=AgentTurn,
                    max_retries=0,
                    messages=messages,
                )

                return result

            except Exception as exc:
                last_error = exc

        raise RuntimeError(
            "LLM failed to produce valid structured output after "
            f"{MAX_OUTPUT_ATTEMPTS} attempts."
        ) from last_error
