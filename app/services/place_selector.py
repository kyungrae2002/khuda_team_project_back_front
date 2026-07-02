"""Two-stage place selection: (1) an objective code-based filter/score over
Google Places candidates (rating, review count, distance from other
confirmed places in the session), then (2) an LLM pass (OpenAI) that picks
among the filtered candidates based on the traveler's stated
wishlist/constraints, with a one-sentence reason grounded in the
conversation."""

import math
from dataclasses import dataclass
from typing import Protocol, Sequence

import openai

from app.models.place import Place
from app.models.slot import SlotField, SlotStatus
from app.schemas.place_selection import PlaceSelection, PlaceSelectionOutput
from app.services.geo import haversine_km as _haversine_km
from app.services.llm_client import LLMCallError, call_structured, default_client

DEFAULT_MODEL = "gpt-4o"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_MAX_RETRIES = 2

# Floor applied to distance_km before taking 1/distance, so two candidates at
# (near-)identical coordinates don't blow the distance term up toward infinity.
_MIN_DISTANCE_KM = 0.01

_RELEVANT_FIELDS: tuple[SlotField, ...] = (SlotField.wishlist, SlotField.constraint)


class SlotLike(Protocol):
    field: SlotField
    value: str
    status: SlotStatus


@dataclass
class ScoredPlace:
    place: Place
    score: float
    distance_km: float | None


class PlaceSelectionError(RuntimeError):
    """Raised when LLM-based place selection fails after exhausting all retries."""


def _min_distance_km(place: Place, reference_places: Sequence[Place]) -> float | None:
    distances = [
        _haversine_km(place.lat, place.lng, ref.lat, ref.lng)
        for ref in reference_places
        if ref.place_id != place.place_id
    ]
    return min(distances) if distances else None


def _score(
    place: Place,
    distance_km: float | None,
    w_rating: float,
    w_review_count: float,
    w_distance: float,
) -> float:
    rating_term = w_rating * place.rating
    review_term = w_review_count * math.log(max(place.review_count, 1))
    distance_term = (
        0.0 if distance_km is None else w_distance * (1.0 / max(distance_km, _MIN_DISTANCE_KM))
    )
    return rating_term + review_term + distance_term


def filter_by_score(
    places: Sequence[Place],
    *,
    reference_places: Sequence[Place] = (),
    min_rating: float = 3.5,
    min_review_count: int = 10,
    w_rating: float = 1.0,
    w_review_count: float = 1.0,
    w_distance: float = 1.0,
    top_n: int | None = None,
) -> list[ScoredPlace]:
    scored: list[ScoredPlace] = []
    for place in places:
        if place.rating is None or place.rating < min_rating:
            continue
        if place.review_count is None or place.review_count < min_review_count:
            continue

        distance_km = _min_distance_km(place, reference_places)
        scored.append(
            ScoredPlace(
                place=place,
                score=_score(place, distance_km, w_rating, w_review_count, w_distance),
                distance_km=distance_km,
            )
        )

    scored.sort(key=lambda scored_place: scored_place.score, reverse=True)
    return scored[:top_n] if top_n is not None else scored


_SYSTEM_PROMPT = """당신은 여행 일정에 포함할 장소를 후보 목록에서 골라주는 도우미입니다.

입력으로 다음 두 가지를 받습니다:
1. 후보 장소 목록 (place_id, 이름, 평점, 리뷰 수, 그리고 있다면 다른 확정 장소와의 거리(km))
2. 대화에서 확정된 wishlist(먹킷리스트)와 constraint(제약사항) 슬롯

규칙:
1. 후보 목록에 있는 place_id만 선택하세요. 목록에 없는 장소를 지어내면 안 됩니다.
2. 각 장소를 고른 이유(selection_reason)는 wishlist/constraint 슬롯의 실제 내용과 연결해
   한 문장으로 작성하세요. 막연한 칭찬("평점이 높아서")보다는 대화에서 드러난 취향과
   왜 이 장소가 그 취향에 맞는지를 설명하세요. 평점/리뷰수/거리 같은 객관적 지표도
   보조 근거로 함께 언급할 수 있습니다.
3. 모든 후보를 다 고를 필요는 없습니다 — 대화 취향과 맞지 않는 후보는 제외해도 됩니다.
4. wishlist/constraint 슬롯이 비어 있다면, 후보들의 평점/리뷰수/거리 등 객관적 기준만으로
   한 문장씩 이유를 작성하세요.

반드시 주어진 JSON 스키마에 맞는 형식으로만 응답하세요."""


def _format_candidates(candidates: Sequence[ScoredPlace]) -> str:
    lines = []
    for scored_place in candidates:
        place = scored_place.place
        parts = [f"place_id={place.place_id}", f"이름={place.name}"]
        if place.rating is not None:
            parts.append(f"평점={place.rating}")
        if place.review_count is not None:
            parts.append(f"리뷰수={place.review_count}")
        if scored_place.distance_km is not None:
            parts.append(f"거리={scored_place.distance_km:.1f}km")
        lines.append(", ".join(parts))
    return "\n".join(lines)


def _format_slots(slots: Sequence[SlotLike]) -> str:
    relevant = [
        slot
        for slot in slots
        if slot.status == SlotStatus.confirmed and slot.field in _RELEVANT_FIELDS
    ]
    if not relevant:
        return "(확정된 wishlist/constraint 없음)"
    return "\n".join(f"{slot.field.value}: {slot.value}" for slot in relevant)


def _build_user_prompt(candidates: Sequence[ScoredPlace], slots: Sequence[SlotLike]) -> str:
    return (
        f"[후보 장소 목록]\n{_format_candidates(candidates)}\n\n"
        f"[대화에서 확정된 슬롯]\n{_format_slots(slots)}"
    )


class PlaceSelector:
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

    def select(
        self, candidates: Sequence[ScoredPlace], slots: Sequence[SlotLike]
    ) -> list[PlaceSelection]:
        if not candidates:
            return []

        prompt = _build_user_prompt(candidates, slots)
        valid_place_ids = {scored_place.place.place_id for scored_place in candidates}

        try:
            output: PlaceSelectionOutput = call_structured(
                self._client,
                model=self._model,
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=prompt,
                output_model=PlaceSelectionOutput,
                schema_name="place_selection",
                max_tokens=self._max_tokens,
                max_retries=self._max_retries,
                retry_delay_seconds=self._retry_delay_seconds,
            )
        except LLMCallError as exc:
            raise PlaceSelectionError(str(exc)) from exc

        # Defense against hallucinated place_ids that aren't in the candidate set.
        return [
            selection for selection in output.selections if selection.place_id in valid_place_ids
        ]


place_selector = PlaceSelector()


def select_places(
    candidates: Sequence[ScoredPlace], slots: Sequence[SlotLike]
) -> list[PlaceSelection]:
    return place_selector.select(candidates, slots)
