"""Orchestrates the full itinerary-generation pipeline for
POST /sessions/{id}/itinerary: confirmed slots -> Places search queries ->
Places API (cached) -> two-stage place selection -> route build + critique/fix
loop -> narration. Keeps the API route thin and the individual services
independently testable."""

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessage
from app.models.place import Place
from app.models.slot import Slot, SlotField
from app.schemas.query_builder import PlaceCategory, PlaceQuery
from app.services.date_resolver import DateResolutionError, resolve_travel_date
from app.services.itinerary_builder import ItineraryResult, build_and_validate_itinerary
from app.services.narrator import ItineraryNarrative, narrate
from app.services.place_selector import filter_by_score, select_places
from app.services.places_client import batch_search, get_or_fetch_place
from app.services.query_builder import build_place_queries, resolve_slot_value


class PipelineError(RuntimeError):
    """Raised when the itinerary pipeline cannot proceed at all (e.g. missing
    critical slots, or no places survived search/filtering)."""


@dataclass
class PipelineResult:
    narrative: ItineraryNarrative
    itinerary_result: ItineraryResult


# Guaranteed category coverage on top of whatever the LLM-driven query_builder
# derives from wishlist/constraint, so a day always has enough breakfast/lunch/
# dinner and attraction candidates to choose from even when the conversation
# only mentioned one or two specific wishlist items.
_BASELINE_QUERY_TEMPLATES: tuple[tuple[str, PlaceCategory], ...] = (
    ("{destination} 브런치 맛집", PlaceCategory.cafe),
    ("{destination} 점심 맛집", PlaceCategory.restaurant),
    ("{destination} 저녁 맛집", PlaceCategory.restaurant),
    ("{destination} 가볼만한 곳", PlaceCategory.tourist_attraction),
    ("{destination} 관광 명소", PlaceCategory.tourist_attraction),
)


def _build_baseline_queries(destination: str) -> list[PlaceQuery]:
    return [
        PlaceQuery(query_text=text.format(destination=destination), search_type="text", category=category)
        for text, category in _BASELINE_QUERY_TEMPLATES
    ]


def _merge_queries(
    llm_queries: Sequence[PlaceQuery], baseline_queries: Sequence[PlaceQuery]
) -> list[PlaceQuery]:
    seen = {(q.query_text, q.search_type, q.category) for q in llm_queries}
    merged = list(llm_queries)
    for query in baseline_queries:
        key = (query.query_text, query.search_type, query.category)
        if key not in seen:
            seen.add(key)
            merged.append(query)
    return merged


def _resolve_destination_location(
    db: Session, slots: Sequence[Slot]
) -> tuple[float, float] | None:
    """Best-effort anchor point for "nearby" search_type queries, which need a
    center that PlaceQuery itself doesn't carry. Resolved via a plain text
    search for the destination name."""
    destination = resolve_slot_value(slots, SlotField.destination)
    if destination is None:
        return None

    anchor_query = PlaceQuery(
        query_text=destination, search_type="text", category=PlaceCategory.tourist_attraction
    )
    anchor_places = get_or_fetch_place(db, anchor_query)
    if not anchor_places:
        return None
    return anchor_places[0].lat, anchor_places[0].lng


def _resolve_start_date(db: Session, session_id: int, slots: Sequence[Slot]) -> date:
    """The itinerary's actual start date, not the date it happens to be
    generated on — business-hours validation needs the trip's real
    day-of-week. Falls back to today if the date slot is missing/unresolvable
    so a flaky resolution never blocks itinerary generation outright."""
    raw_date_value = resolve_slot_value(slots, SlotField.date)
    if raw_date_value is None:
        return date.today()

    latest_message = (
        db.query(ChatMessage)
        .filter_by(session_id=session_id)
        .order_by(ChatMessage.timestamp.desc())
        .first()
    )
    reference_date = latest_message.timestamp.date() if latest_message else date.today()

    try:
        resolved = resolve_travel_date(raw_date_value, reference_date)
    except DateResolutionError:
        return date.today()
    return resolved or date.today()


def generate_itinerary(
    db: Session, session_id: int, slots: Sequence[Slot], days: int
) -> PipelineResult:
    query_result = build_place_queries(slots)
    if query_result.missing_critical_slots:
        missing = ", ".join(field.value for field in query_result.missing_critical_slots)
        raise PipelineError(f"필수 슬롯이 비어 있어 장소를 검색할 수 없습니다: {missing}")

    location = _resolve_destination_location(db, slots)

    destination = resolve_slot_value(slots, SlotField.destination)
    baseline_queries = _build_baseline_queries(destination) if destination else []
    search_queries = _merge_queries(query_result.queries, baseline_queries)

    candidate_places: list[Place] = []
    for places in batch_search(db, search_queries, location=location):
        candidate_places.extend(places)
    unique_places = list({place.id: place for place in candidate_places}.values())
    if not unique_places:
        raise PipelineError("검색된 장소가 없습니다.")

    scored = filter_by_score(unique_places)
    if not scored:
        raise PipelineError("평점/리뷰 수 기준을 만족하는 장소가 없습니다.")

    selections = select_places(scored, slots, days=days)
    google_id_to_place = {scored_place.place.place_id: scored_place.place for scored_place in scored}
    selected_places = [
        google_id_to_place[selection.place_id]
        for selection in selections
        if selection.place_id in google_id_to_place
    ]
    if not selected_places:
        raise PipelineError("대화 취향에 맞는 장소가 선정되지 않았습니다.")

    selection_reasons = {
        google_id_to_place[selection.place_id].id: selection.selection_reason
        for selection in selections
        if selection.place_id in google_id_to_place
    }

    start_date = _resolve_start_date(db, session_id, slots)
    itinerary_result = build_and_validate_itinerary(
        db, session_id, selected_places, days, start_date=start_date
    )

    places_by_id = {place.id: place for place in selected_places}
    narrative = narrate(itinerary_result.itinerary, places_by_id, selection_reasons)

    return PipelineResult(narrative=narrative, itinerary_result=itinerary_result)
