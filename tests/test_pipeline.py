import unittest

from app.models.place import Place
from app.services.pipeline import (
    DEFAULT_MAX_DESTINATION_DISTANCE_KM,
    MIN_PLACES_PER_DAY,
    _filter_by_destination_distance,
    _top_up_selected_places,
)
from app.services.place_selector import ScoredPlace

_JEJU_CITY = (33.4996, 126.5312)
# A real place ~437km from Jeju (Seongnam) — the exact mismatch this filter
# exists to catch: a text search for "제주도 점심 맛집" matched a same-themed
# restaurant nowhere near the actual destination.
_SEONGNAM = (37.3975, 127.1132)


def _place(place_id: str, lat: float, lng: float, *, id: int | None = None) -> Place:
    return Place(id=id, place_id=place_id, name=f"place-{place_id}", lat=lat, lng=lng)


class TestFilterByDestinationDistance(unittest.TestCase):
    def test_keeps_places_within_range(self) -> None:
        nearby = _place("nearby", *_JEJU_CITY)

        result = _filter_by_destination_distance([nearby], _JEJU_CITY)

        self.assertEqual(result, [nearby])

    def test_rejects_place_far_outside_destination_region(self) -> None:
        far_away = _place("far", *_SEONGNAM)

        result = _filter_by_destination_distance([far_away], _JEJU_CITY)

        self.assertEqual(result, [])

    def test_respects_custom_max_distance(self) -> None:
        borderline = _place("borderline", 34.0, 126.5)  # ~55km from Jeju city

        kept = _filter_by_destination_distance([borderline], _JEJU_CITY, max_distance_km=100.0)
        rejected = _filter_by_destination_distance([borderline], _JEJU_CITY, max_distance_km=10.0)

        self.assertEqual(kept, [borderline])
        self.assertEqual(rejected, [])

    def test_skips_filtering_when_no_anchor_location_resolved(self) -> None:
        far_away = _place("far", *_SEONGNAM)

        result = _filter_by_destination_distance([far_away], None)

        self.assertEqual(result, [far_away])

    def test_default_threshold_is_100km(self) -> None:
        self.assertEqual(DEFAULT_MAX_DESTINATION_DISTANCE_KM, 100.0)


class TestTopUpSelectedPlaces(unittest.TestCase):
    def test_tops_up_when_llm_under_selected(self) -> None:
        # Regression test: select_places is only prompt-instructed to reach
        # days*5, not guaranteed to — an under-selection starves some days
        # of enough stops to reach evening regardless of scheduling.
        scored = [
            ScoredPlace(place=_place(f"p{i}", 0.0, float(i), id=i), score=10.0 - i, distance_km=None)
            for i in range(1, 8)
        ]
        selected = [scored[0].place, scored[1].place]  # only 2, days=1 needs 5

        topped_up = _top_up_selected_places(scored, selected, days=1)

        self.assertEqual(len(topped_up), MIN_PLACES_PER_DAY)
        # Original selections kept, filled from the highest-scoring remainder.
        self.assertEqual(topped_up[:2], selected)
        self.assertEqual({p.id for p in topped_up}, {1, 2, 3, 4, 5})

    def test_no_op_when_already_at_or_above_target(self) -> None:
        scored = [ScoredPlace(place=_place(f"p{i}", 0.0, float(i), id=i), score=1.0, distance_km=None) for i in range(1, 6)]
        selected = [sp.place for sp in scored]  # exactly days*5 for days=1

        topped_up = _top_up_selected_places(scored, selected, days=1)

        self.assertEqual(topped_up, selected)

    def test_degrades_gracefully_when_not_enough_candidates_exist(self) -> None:
        scored = [ScoredPlace(place=_place("p1", 0.0, 0.0, id=1), score=1.0, distance_km=None)]
        selected = [scored[0].place]

        topped_up = _top_up_selected_places(scored, selected, days=4)  # needs 20, only 1 exists

        self.assertEqual(topped_up, selected)


if __name__ == "__main__":
    unittest.main()
