"""Converts confirmed travel slots (destination/wishlist/constraint) into
Google Places search queries using OpenAI (a small/cheap model tier, since
this task is simple string composition + category classification)."""

from typing import Protocol, Sequence

import openai

from app.models.slot import SlotField, SlotStatus
from app.schemas.query_builder import PlaceQueriesOutput, QueryBuildResult
from app.services.llm_client import LLMCallError, call_structured, default_client

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_MAX_RETRIES = 2

_CRITICAL_FIELDS: tuple[SlotField, ...] = (SlotField.destination,)
_RELEVANT_FIELDS: tuple[SlotField, ...] = (
    SlotField.destination,
    SlotField.wishlist,
    SlotField.constraint,
)

_SYSTEM_PROMPT = """당신은 확정된 여행 슬롯 정보를 Google Places API 검색 쿼리로 변환하는
도우미입니다.

입력으로 destination(목적지), wishlist(먹킷리스트), constraint(제약사항) 슬롯의 확정된
값들을 "field: value" 형식의 목록으로 받습니다.

규칙:
1. wishlist 항목마다 destination과 결합한 자연스러운 검색어(query_text)를 만드세요.
   예: destination="부산", wishlist="회 맛집" → query_text="부산 회 맛집"
2. constraint(예: "비건 위주로", "아이 동반", "실내 위주")는 관련 있는 쿼리의 문구에
   자연스럽게 반영하세요. 특정 wishlist와 관련 없는 일반적인 제약이라면 별도의 쿼리를
   추가로 만들어도 됩니다.
3. search_type은 다음 기준으로 정하세요:
   - "부산 회 맛집"처럼 구체적인 대상이 있는 텍스트 검색이 자연스러우면 "text"
   - "목적지 주변 카페", "근처 관광지"처럼 위치 기반 주변 검색이 더 적절하면 "nearby"
4. category는 다음 중 검색 의도에 가장 알맞은 하나만 선택하세요:
   restaurant, cafe, bakery, bar, night_club, tourist_attraction, museum, art_gallery,
   park, amusement_park, zoo, aquarium, shopping_mall, lodging, spa, movie_theater.
   뚜렷하게 맞는 것이 없으면 tourist_attraction을 사용하세요.
5. wishlist와 constraint가 모두 없고 destination만 있다면, destination만으로 일반적인
   관광 명소 검색 쿼리를 1개만 생성하세요.
6. 사용자가 말하지 않은 장소나 취향을 지어내지 마세요.

반드시 주어진 JSON 스키마에 맞는 형식으로만 응답하세요."""


class SlotLike(Protocol):
    field: SlotField
    value: str
    status: SlotStatus
    confidence: float


class QueryBuildError(RuntimeError):
    """Raised when Google Places query generation fails after exhausting all retries."""


def _best_slot(slots: Sequence[SlotLike], field: SlotField) -> SlotLike | None:
    """A confirmed slot for this field if one exists, otherwise the
    highest-confidence entry regardless of status (conflict/undecided) —
    resolves a genuine disagreement in the conversation (e.g. two candidate
    destinations neither side backed down on) by picking the most likely
    option instead of blocking generation entirely."""
    field_slots = [slot for slot in slots if slot.field == field]
    if not field_slots:
        return None
    confirmed = [slot for slot in field_slots if slot.status == SlotStatus.confirmed]
    if confirmed:
        return confirmed[0]
    return max(field_slots, key=lambda slot: slot.confidence)


def resolve_slot_value(slots: Sequence[SlotLike], field: SlotField) -> str | None:
    best = _best_slot(slots, field)
    return best.value if best is not None else None


def _find_missing_critical_slots(slots: Sequence[SlotLike]) -> list[SlotField]:
    return [field for field in _CRITICAL_FIELDS if _best_slot(slots, field) is None]


def _build_prompt_slots(slots: Sequence[SlotLike]) -> list[SlotLike]:
    confirmed = [
        slot
        for slot in slots
        if slot.status == SlotStatus.confirmed and slot.field in _RELEVANT_FIELDS
    ]
    confirmed_fields = {slot.field for slot in confirmed}
    for field in _CRITICAL_FIELDS:
        if field not in confirmed_fields:
            best = _best_slot(slots, field)
            if best is not None:
                confirmed.append(best)
    return confirmed


def _format_slots(slots: Sequence[SlotLike]) -> str:
    return "\n".join(f"{slot.field.value}: {slot.value}" for slot in slots)


class QueryBuilder:
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

    def build(self, slots: Sequence[SlotLike]) -> QueryBuildResult:
        missing = _find_missing_critical_slots(slots)
        if missing:
            return QueryBuildResult(missing_critical_slots=missing)

        prompt = _format_slots(_build_prompt_slots(slots))

        try:
            output: PlaceQueriesOutput = call_structured(
                self._client,
                model=self._model,
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=prompt,
                output_model=PlaceQueriesOutput,
                schema_name="place_queries",
                max_tokens=self._max_tokens,
                max_retries=self._max_retries,
                retry_delay_seconds=self._retry_delay_seconds,
            )
        except LLMCallError as exc:
            raise QueryBuildError(str(exc)) from exc

        return QueryBuildResult(queries=output.queries)


query_builder = QueryBuilder()


def build_place_queries(slots: Sequence[SlotLike]) -> QueryBuildResult:
    return query_builder.build(slots)
