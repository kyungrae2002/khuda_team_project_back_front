"""Rule-based validation of a built itinerary: zigzag/backtracking routes,
arrivals outside business hours, and insufficient buffer time between stops.

Violation.item_id is the offending entry's Place.id (== ItineraryItem.place_id),
not ItineraryItem.id — itinerary items may not be persisted yet while the
build/critique loop is still running, so Place.id is the only stable
identifier available at every stage."""

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

from app.models.itinerary_item import ItineraryItem
from app.models.place import Place
from app.services.geo import haversine_km
from app.services.opening_hours import get_opening_period

_BACKTRACK_ANGLE_DEGREES = 150.0
_MIN_BUFFER_MINUTES = 15.0
_DEFAULT_AVERAGE_SPEED_KMH = 30.0


@dataclass
class Violation:
    type: str
    item_id: int
    description: str


def _by_day(itinerary: Sequence[ItineraryItem]) -> dict[int, list[ItineraryItem]]:
    by_day: dict[int, list[ItineraryItem]] = {}
    for item in itinerary:
        by_day.setdefault(item.day_index, []).append(item)
    for items in by_day.values():
        items.sort(key=lambda it: it.order_in_day)
    return by_day


def _segments_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> bool:
    def ccw(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    return ccw(p1, p3, p4) != ccw(p2, p3, p4) and ccw(p1, p2, p3) != ccw(p1, p2, p4)


def _turn_angle_degrees(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> float:
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    mag1, mag2 = math.hypot(*v1), math.hypot(*v2)
    if mag1 == 0 or mag2 == 0:
        return 180.0
    cos_angle = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (mag1 * mag2)))
    return math.degrees(math.acos(cos_angle))


def check_round_trip(
    itinerary: Sequence[ItineraryItem], places_by_id: dict[int, Place]
) -> list[Violation]:
    violations: list[Violation] = []

    for day_index, items in _by_day(itinerary).items():
        if len(items) < 3:
            continue
        points = [(places_by_id[it.place_id].lng, places_by_id[it.place_id].lat) for it in items]

        for i in range(len(points) - 1):
            for j in range(i + 2, len(points) - 1):
                if _segments_intersect(points[i], points[i + 1], points[j], points[j + 1]):
                    violations.append(
                        Violation(
                            type="round_trip",
                            item_id=items[j + 1].place_id,
                            description=(
                                f"{day_index}일차 이동 경로가 교차합니다: "
                                f"{items[i].place_id}→{items[i + 1].place_id} 구간과 "
                                f"{items[j].place_id}→{items[j + 1].place_id} 구간이 겹칩니다."
                            ),
                        )
                    )

        for i in range(1, len(points) - 1):
            # angle is 0 for a straight continuation and 180 for a full reversal;
            # a large angle means the path sharply doubled back on itself.
            angle = _turn_angle_degrees(points[i - 1], points[i], points[i + 1])
            if angle > _BACKTRACK_ANGLE_DEGREES:
                violations.append(
                    Violation(
                        type="round_trip",
                        item_id=items[i].place_id,
                        description=(
                            f"{day_index}일차: {items[i - 1].place_id}→{items[i].place_id}→"
                            f"{items[i + 1].place_id} 구간이 급격히 되돌아가는 지그재그 경로입니다 "
                            f"(회전각 {angle:.0f}도)."
                        ),
                    )
                )

    return violations


def check_business_hours(
    itinerary: Sequence[ItineraryItem], places_by_id: dict[int, Place]
) -> list[Violation]:
    violations: list[Violation] = []
    for item in itinerary:
        place = places_by_id[item.place_id]
        period = get_opening_period(place, item.arrival_time.date())
        if period is None:
            continue
        open_time, close_time = period
        arrival = item.arrival_time.time()
        if arrival < open_time or arrival > close_time:
            violations.append(
                Violation(
                    type="business_hours",
                    item_id=item.place_id,
                    description=(
                        f"{place.name} 도착 시각 {arrival.strftime('%H:%M')}이(가) "
                        f"영업시간({open_time.strftime('%H:%M')}~{close_time.strftime('%H:%M')}) "
                        f"밖입니다."
                    ),
                )
            )
    return violations


def check_buffer(
    itinerary: Sequence[ItineraryItem],
    places_by_id: dict[int, Place],
    *,
    average_speed_kmh: float = _DEFAULT_AVERAGE_SPEED_KMH,
    min_buffer_minutes: float = _MIN_BUFFER_MINUTES,
) -> list[Violation]:
    violations: list[Violation] = []
    for day_index, items in _by_day(itinerary).items():
        for previous, current in zip(items, items[1:]):
            prev_place = places_by_id[previous.place_id]
            curr_place = places_by_id[current.place_id]
            travel_km = haversine_km(prev_place.lat, prev_place.lng, curr_place.lat, curr_place.lng)
            travel_minutes = (travel_km / average_speed_kmh) * 60

            departure = previous.arrival_time + timedelta(minutes=previous.duration_minutes)
            available_buffer = (
                current.arrival_time - departure
            ).total_seconds() / 60 - travel_minutes

            # Small epsilon guards against float round-trip error through
            # timedelta's microsecond-precision storage (see build_route's
            # scheduling), which can push an exactly-at-threshold buffer a
            # hair below min_buffer_minutes.
            if available_buffer < min_buffer_minutes - 1e-6:
                violations.append(
                    Violation(
                        type="buffer",
                        item_id=current.place_id,
                        description=(
                            f"{day_index}일차: {prev_place.name}에서 {curr_place.name}(으)로 이동 후 "
                            f"여유 시간이 {available_buffer:.0f}분으로 부족합니다 "
                            f"(최소 {min_buffer_minutes:.0f}분 필요)."
                        ),
                    )
                )
    return violations


def run_all_validators(
    itinerary: Sequence[ItineraryItem], places_by_id: dict[int, Place]
) -> list[Violation]:
    return [
        *check_round_trip(itinerary, places_by_id),
        *check_business_hours(itinerary, places_by_id),
        *check_buffer(itinerary, places_by_id),
    ]
