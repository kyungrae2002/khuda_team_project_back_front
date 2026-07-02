"""Resolves a free-text date slot value (e.g. "21일", "다음주 금요일") into a
concrete calendar date, using the conversation's own timestamps as the
reference "today" — this matters because slot_extractor captures date slots
as unconstrained natural language, and business-hours validation
(app.services.opening_hours) needs the actual day-of-week of the trip, not
today's."""

from datetime import date

import openai

from app.schemas.date_resolution import DateResolution
from app.services.llm_client import LLMCallError, call_structured, default_client

DEFAULT_MODEL = "gpt-4o"
DEFAULT_MAX_TOKENS = 256
DEFAULT_MAX_RETRIES = 2

_SYSTEM_PROMPT = """당신은 여행 대화에서 언급된 날짜 표현을 실제 캘린더 날짜로 변환하는
도우미입니다.

입력으로 대화가 실제로 일어난 기준 날짜(reference_date)와, 그 대화에서 나온 날짜 표현
원문(raw_value)을 받습니다.

규칙:
1. "21일"처럼 일(day)만 있으면 reference_date와 같은 달의 그 날짜로 해석하세요. 단,
   그 날짜의 일(day) 숫자가 reference_date의 일(day) 숫자보다 "작거나 같으면"(이미
   지났거나 오늘이면) 다음 달로 해석하고, "크면"(아직 오지 않았으면) 같은 달로
   해석하세요. 날짜 비교는 오직 일(day) 숫자만으로 판단하고, 몇 주 이상 남았는지
   같은 다른 기준은 쓰지 마세요.
   예시 1: reference_date=2025-06-20, raw_value="21일" → 21 > 20이므로 같은 달
   → resolved_date="2025-06-21"
   예시 2: reference_date=2025-06-20, raw_value="15일" → 15 <= 20이므로 다음 달
   → resolved_date="2025-07-15"
2. "7월 21일"처럼 월/일이 있으면 reference_date와 같은 해로 해석하되, 이미 지난
   날짜라면 다음 해로 해석하세요.
3. "다음주 금요일", "이번 주말", "내일" 같은 상대적 표현은 reference_date를 기준으로
   계산하세요.
4. "2025-07-21"처럼 이미 완전한 날짜 형식이면 그대로 사용하세요.
5. 명확히 해석할 수 없는 표현(예: "나중에 정하자", "미정")이면 could_resolve를
   false로 하고 resolved_date는 빈 문자열로 두세요.

반드시 주어진 JSON 스키마에 맞는 형식으로만 응답하세요."""


class DateResolutionError(RuntimeError):
    """Raised when date resolution fails after exhausting all retries."""


def _build_user_prompt(raw_value: str, reference_date: date) -> str:
    return f"reference_date: {reference_date.isoformat()}\nraw_value: {raw_value}"


class DateResolver:
    def __init__(
        self,
        client: openai.OpenAI | None = None,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        self._client = client or default_client()
        self._model = model
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds

    def resolve(self, raw_value: str, reference_date: date) -> date | None:
        try:
            output: DateResolution = call_structured(
                self._client,
                model=self._model,
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=_build_user_prompt(raw_value, reference_date),
                output_model=DateResolution,
                schema_name="date_resolution",
                max_tokens=self._max_tokens,
                max_retries=self._max_retries,
                retry_delay_seconds=self._retry_delay_seconds,
            )
        except LLMCallError as exc:
            raise DateResolutionError(str(exc)) from exc

        if not output.could_resolve:
            return None
        try:
            return date.fromisoformat(output.resolved_date)
        except ValueError:
            return None


date_resolver = DateResolver()


def resolve_travel_date(raw_value: str, reference_date: date) -> date | None:
    return date_resolver.resolve(raw_value, reference_date)
