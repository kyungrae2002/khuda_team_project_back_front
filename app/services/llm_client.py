"""Shared OpenAI structured-output call helper: the retry-with-backoff loop,
strict JSON-schema request shape, and refusal/truncation handling used
identically by every LLM-backed service (slot_extractor, query_builder,
place_selector, itinerary_builder, narrator).

Each caller keeps its own domain-specific exception type (SlotExtractionError,
QueryBuildError, ...) — this module raises a generic LLMCallError on
exhaustion, which callers catch and re-wrap so existing error handling
(e.g. app/api/sessions.py) doesn't need to change.

NOTE ON MODEL NAMES: "gpt-4o" / "gpt-4o-mini" below are the safest widely
available OpenAI models as of this writing. Swap the DEFAULT_MODEL constant
in each service file if your account targets a different model."""

import json
import time
from typing import TypeVar

import openai
from pydantic import BaseModel, ValidationError

from app.core.config import settings

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMCallError(RuntimeError):
    """Raised when an OpenAI structured-output call fails after exhausting all retries."""


def default_client() -> openai.OpenAI:
    # Unlike anthropic.Anthropic, openai.OpenAI raises immediately on an empty
    # api_key instead of deferring to the first request. Since every service
    # singleton constructs its client at import time, an unset OPENAI_API_KEY
    # would otherwise crash the whole app on import — fall back to a
    # placeholder so construction succeeds and the real failure (a clear auth
    # error) only surfaces when a call is actually attempted.
    return openai.OpenAI(api_key=settings.OPENAI_API_KEY or "sk-not-configured")


def call_structured(
    client: openai.OpenAI,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    output_model: type[ModelT],
    schema_name: str,
    max_tokens: int,
    max_retries: int,
    retry_delay_seconds: float,
) -> ModelT:
    schema = output_model.model_json_schema()

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                max_completion_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "schema": schema, "strict": True},
                },
            )
            return _parse_response(response, output_model)
        except (json.JSONDecodeError, ValidationError, ValueError, openai.APIError) as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(retry_delay_seconds)

    raise LLMCallError(
        f"OpenAI 구조화 출력 호출이 {max_retries + 1}회 시도 후 실패했습니다: {last_error}"
    ) from last_error


def _parse_response(response: "openai.types.chat.ChatCompletion", output_model: type[ModelT]) -> ModelT:
    choice = response.choices[0]
    message = choice.message

    if getattr(message, "refusal", None):
        raise ValueError(f"모델이 안전 정책으로 요청을 거부했습니다 (refusal): {message.refusal}")

    if choice.finish_reason == "length":
        raise ValueError("응답이 max_tokens 제한으로 잘렸습니다")

    if message.content is None:
        raise ValueError("응답에 content가 없습니다")

    data = json.loads(message.content)
    return output_model.model_validate(data)
