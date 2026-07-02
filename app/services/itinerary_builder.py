"""Builds a day-by-day itinerary route from selected places, then runs an
LLM-driven critique/fix loop (OpenAI) against the rule violations found by
app.services.validator, bounded to at most 2 fix attempts so the loop can
never run unbounded."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Sequence

import openai
from sqlalchemy.orm import Session

from app.models.itinerary_item import ItineraryItem, ReservationNeeded
from app.models.place import Place
from app.models.validation_log import ValidationLog
from app.schemas.itinerary_fix import ItineraryFixSuggestion
from app.services.geo import haversine_km
from app.services.llm_client import LLMCallError, call_structured, default_client
from app.services.opening_hours import get_opening_period
from app.services.validator import Violation, run_all_validators

DEFAULT_MODEL = "gpt-4o"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_MAX_LLM_RETRIES = 2
MAX_CRITIQUE_ITERATIONS = 2

DEFAULT_DAY_START_TIME = time(9, 0)
DEFAULT_DURATION_MINUTES = 90
DEFAULT_AVERAGE_SPEED_KMH = 30.0
# Slack added after travel, on top of the raw travel time, before the next
# visit starts. Matches validator.check_buffer's default min_buffer_minutes,
# so a freshly-built route doesn't trip the buffer check on its own.
DEFAULT_BUFFER_MINUTES = 15.0


@dataclass
class ItineraryResult:
    itinerary: list[ItineraryItem]
    violations: list[Violation]
    iterations_used: int


class ItineraryFixError(RuntimeError):
    """Raised when the LLM-based fix suggestion fails after exhausting all retries."""


# ---------------------------------------------------------------------------
# Stage 1: route computation (pure code)
# ---------------------------------------------------------------------------


def _kmeans_cluster(
    places: Sequence[Place], k: int, *, max_iterations: int = 20
) -> list[list[Place]]:
    if not places:
        return [[] for _ in range(max(k, 0))]

    k = max(1, min(k, len(places)))
    sorted_places = sorted(places, key=lambda p: (p.lat, p.lng))
    step = max(1, len(sorted_places) // k)
    centroids = [(p.lat, p.lng) for p in sorted_places[::step][:k]]
    while len(centroids) < k:
        centroids.append(centroids[-1])

    assignment = [0] * len(places)
    for _ in range(max_iterations):
        changed = False
        for i, place in enumerate(places):
            distances = [
                haversine_km(place.lat, place.lng, c_lat, c_lng) for c_lat, c_lng in centroids
            ]
            nearest = distances.index(min(distances))
            if assignment[i] != nearest:
                assignment[i] = nearest
                changed = True

        for cluster_idx in range(k):
            members = [places[i] for i in range(len(places)) if assignment[i] == cluster_idx]
            if members:
                centroids[cluster_idx] = (
                    sum(p.lat for p in members) / len(members),
                    sum(p.lng for p in members) / len(members),
                )

        if not changed:
            break

    clusters: list[list[Place]] = [[] for _ in range(k)]
    for i, place in enumerate(places):
        clusters[assignment[i]].append(place)
    return clusters


def _nearest_neighbor_order(places: Sequence[Place]) -> list[Place]:
    if not places:
        return []
    remaining = list(places)
    ordered = [remaining.pop(0)]
    while remaining:
        last = ordered[-1]
        distances = [haversine_km(last.lat, last.lng, p.lat, p.lng) for p in remaining]
        ordered.append(remaining.pop(distances.index(min(distances))))
    return ordered


def _schedule_day_groups(
    day_groups: Sequence[Sequence[Place]],
    *,
    start_date: date,
    day_start_time: time,
    default_duration_minutes: int,
    average_speed_kmh: float,
    buffer_minutes: float = DEFAULT_BUFFER_MINUTES,
) -> list[ItineraryItem]:
    items: list[ItineraryItem] = []

    for day_index, group in enumerate(day_groups):
        day_date = start_date + timedelta(days=day_index)
        current_time = datetime.combine(day_date, day_start_time)
        previous_place: Place | None = None

        for order_in_day, place in enumerate(group):
            if previous_place is not None:
                travel_km = haversine_km(
                    previous_place.lat, previous_place.lng, place.lat, place.lng
                )
                travel_minutes = (travel_km / average_speed_kmh) * 60
                current_time += timedelta(minutes=travel_minutes + buffer_minutes)

            period = get_opening_period(place, day_date)
            if period is not None:
                open_dt = datetime.combine(day_date, period[0])
                if current_time < open_dt:
                    current_time = open_dt

            items.append(
                ItineraryItem(
                    place_id=place.id,
                    day_index=day_index,
                    order_in_day=order_in_day,
                    arrival_time=current_time,
                    duration_minutes=default_duration_minutes,
                    reservation_needed=ReservationNeeded.unnecessary,
                )
            )

            current_time += timedelta(minutes=default_duration_minutes)
            previous_place = place

    return items


def build_route(
    places: Sequence[Place],
    days: int,
    *,
    start_date: date | None = None,
    day_start_time: time = DEFAULT_DAY_START_TIME,
    default_duration_minutes: int = DEFAULT_DURATION_MINUTES,
    average_speed_kmh: float = DEFAULT_AVERAGE_SPEED_KMH,
    buffer_minutes: float = DEFAULT_BUFFER_MINUTES,
) -> list[ItineraryItem]:
    day_groups = [_nearest_neighbor_order(cluster) for cluster in _kmeans_cluster(places, days)]
    return _schedule_day_groups(
        day_groups,
        start_date=start_date or date.today(),
        day_start_time=day_start_time,
        default_duration_minutes=default_duration_minutes,
        average_speed_kmh=average_speed_kmh,
        buffer_minutes=buffer_minutes,
    )


# ---------------------------------------------------------------------------
# Stage 3: LLM critique / fix (Claude Sonnet 5)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """당신은 여행 일정의 동선 문제를 검토하고 수정 방향을 제안하는 도우미입니다.

입력으로 현재 일정(day_index, order_in_day, place_id, 이름, 평점, 리뷰수, 카테고리,
도착시각)과 발견된 규칙 위반 목록(type, item_id, description)을 받습니다.

규칙:
1. 위반을 해결할 수 있도록 day별 방문 순서를 조정하세요. 필요하다면 문제가 되는 장소를
   해당 day의 목록에서 제외해도 됩니다. 단, 입력에 없던 새로운 place_id를 지어내면
   안 됩니다 — 오직 주어진 place_id만 사용하세요.
2. 응답의 days 배열에는 모든 day_index를 포함하고, 각 day의 place_ids는 방문 순서대로
   나열하세요.
3. 최종 일정에 남아있는 모든 장소에 대해 reservation_needed(예약 필요성)를
   required(예약 필수) / recommended(예약 권장) / unnecessary(불필요) 중 하나로
   판정하세요. 장소의 카테고리(음식점/카페/관광지 등), 평점·리뷰 수로 드러나는 인기도,
   그리고 도착 시간대(예: 저녁 시간대 인기 식당은 예약 필요성이 높음)를 함께 고려하세요.

반드시 주어진 JSON 스키마에 맞는 형식으로만 응답하세요."""


def _format_itinerary(itinerary: Sequence[ItineraryItem], places_by_id: dict[int, Place]) -> str:
    lines = []
    for item in sorted(itinerary, key=lambda it: (it.day_index, it.order_in_day)):
        place = places_by_id[item.place_id]
        parts = [
            f"day={item.day_index}",
            f"order={item.order_in_day}",
            f"place_id={place.id}",
            f"이름={place.name}",
        ]
        if place.primary_type:
            parts.append(f"카테고리={place.primary_type}")
        if place.rating is not None:
            parts.append(f"평점={place.rating}")
        if place.review_count is not None:
            parts.append(f"리뷰수={place.review_count}")
        parts.append(f"도착={item.arrival_time.strftime('%Y-%m-%d %H:%M')}")
        lines.append(", ".join(parts))
    return "\n".join(lines)


def _format_violations(violations: Sequence[Violation]) -> str:
    if not violations:
        return "(없음)"
    return "\n".join(f"[{v.type}] place_id={v.item_id}: {v.description}" for v in violations)


def _build_fix_prompt(
    itinerary: Sequence[ItineraryItem],
    violations: Sequence[Violation],
    places_by_id: dict[int, Place],
) -> str:
    return (
        f"[현재 일정]\n{_format_itinerary(itinerary, places_by_id)}\n\n"
        f"[규칙 위반 목록]\n{_format_violations(violations)}"
    )


def _get_fix_suggestion(
    itinerary: Sequence[ItineraryItem],
    violations: Sequence[Violation],
    places_by_id: dict[int, Place],
    *,
    client: openai.OpenAI,
    model: str,
    max_tokens: int,
    max_retries: int,
    retry_delay_seconds: float,
) -> ItineraryFixSuggestion:
    prompt = _build_fix_prompt(itinerary, violations, places_by_id)

    try:
        return call_structured(
            client,
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=prompt,
            output_model=ItineraryFixSuggestion,
            schema_name="itinerary_fix",
            max_tokens=max_tokens,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
        )
    except LLMCallError as exc:
        raise ItineraryFixError(str(exc)) from exc


def _log_validation_iteration(
    db: Session, session_id: int, iteration: int, violations: Sequence[Violation]
) -> None:
    log = ValidationLog(
        session_id=session_id,
        iteration=iteration,
        violations=[
            {"type": v.type, "item_id": v.item_id, "description": v.description}
            for v in violations
        ],
        resolved=len(violations) == 0,
    )
    db.add(log)
    db.commit()


def critique_and_fix(
    db: Session,
    session_id: int,
    places_by_id: dict[int, Place],
    itinerary: list[ItineraryItem],
    violations: list[Violation],
    iteration: int = 0,
    *,
    start_date: date | None = None,
    day_start_time: time = DEFAULT_DAY_START_TIME,
    default_duration_minutes: int = DEFAULT_DURATION_MINUTES,
    average_speed_kmh: float = DEFAULT_AVERAGE_SPEED_KMH,
    buffer_minutes: float = DEFAULT_BUFFER_MINUTES,
    client: openai.OpenAI | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_llm_retries: int = DEFAULT_MAX_LLM_RETRIES,
    retry_delay_seconds: float = 1.0,
) -> ItineraryResult:
    _log_validation_iteration(db, session_id, iteration, violations)

    if not violations or iteration >= MAX_CRITIQUE_ITERATIONS:
        return ItineraryResult(
            itinerary=list(itinerary), violations=list(violations), iterations_used=iteration
        )

    llm_client = client or default_client()
    suggestion = _get_fix_suggestion(
        itinerary,
        violations,
        places_by_id,
        client=llm_client,
        model=model,
        max_tokens=max_tokens,
        max_retries=max_llm_retries,
        retry_delay_seconds=retry_delay_seconds,
    )

    resolved_start_date = start_date or date.today()
    day_groups = [
        [places_by_id[pid] for pid in day_plan.place_ids if pid in places_by_id]
        for day_plan in sorted(suggestion.days, key=lambda d: d.day_index)
    ]
    revised_itinerary = _schedule_day_groups(
        day_groups,
        start_date=resolved_start_date,
        day_start_time=day_start_time,
        default_duration_minutes=default_duration_minutes,
        average_speed_kmh=average_speed_kmh,
        buffer_minutes=buffer_minutes,
    )

    reservation_by_place_id = {r.place_id: r.reservation_needed for r in suggestion.reservations}
    for item in revised_itinerary:
        reservation = reservation_by_place_id.get(item.place_id)
        if reservation is not None:
            item.reservation_needed = ReservationNeeded(reservation)

    new_violations = run_all_validators(revised_itinerary, places_by_id)

    return critique_and_fix(
        db,
        session_id,
        places_by_id,
        revised_itinerary,
        new_violations,
        iteration + 1,
        start_date=resolved_start_date,
        day_start_time=day_start_time,
        default_duration_minutes=default_duration_minutes,
        average_speed_kmh=average_speed_kmh,
        buffer_minutes=buffer_minutes,
        client=llm_client,
        model=model,
        max_tokens=max_tokens,
        max_llm_retries=max_llm_retries,
        retry_delay_seconds=retry_delay_seconds,
    )


def build_and_validate_itinerary(
    db: Session,
    session_id: int,
    places: Sequence[Place],
    days: int,
    *,
    start_date: date | None = None,
    day_start_time: time = DEFAULT_DAY_START_TIME,
    default_duration_minutes: int = DEFAULT_DURATION_MINUTES,
    average_speed_kmh: float = DEFAULT_AVERAGE_SPEED_KMH,
    buffer_minutes: float = DEFAULT_BUFFER_MINUTES,
    client: openai.OpenAI | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_llm_retries: int = DEFAULT_MAX_LLM_RETRIES,
    retry_delay_seconds: float = 1.0,
) -> ItineraryResult:
    places_by_id = {place.id: place for place in places}
    resolved_start_date = start_date or date.today()

    itinerary = build_route(
        places,
        days,
        start_date=resolved_start_date,
        day_start_time=day_start_time,
        default_duration_minutes=default_duration_minutes,
        average_speed_kmh=average_speed_kmh,
        buffer_minutes=buffer_minutes,
    )
    violations = run_all_validators(itinerary, places_by_id)

    return critique_and_fix(
        db,
        session_id,
        places_by_id,
        itinerary,
        violations,
        iteration=0,
        start_date=resolved_start_date,
        day_start_time=day_start_time,
        default_duration_minutes=default_duration_minutes,
        average_speed_kmh=average_speed_kmh,
        buffer_minutes=buffer_minutes,
        client=client,
        model=model,
        max_tokens=max_tokens,
        max_llm_retries=max_llm_retries,
        retry_delay_seconds=retry_delay_seconds,
    )
