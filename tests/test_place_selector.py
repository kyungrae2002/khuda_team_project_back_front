import math
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.place import Place
from app.models.slot import SlotField, SlotStatus
from app.services.place_selector import (
    PlaceSelectionError,
    PlaceSelector,
    ScoredPlace,
    _haversine_km,
    filter_by_score,
)
from tests.openai_fakes import raw_text_response, refusal_response, text_response


def _place(place_id: str, lat: float, lng: float, rating: float | None = 4.5, review_count: int | None = 100) -> Place:
    return Place(place_id=place_id, name=f"place-{place_id}", lat=lat, lng=lng, rating=rating, review_count=review_count)


def _slot(field: SlotField, value: str, status: SlotStatus = SlotStatus.confirmed):
    return SimpleNamespace(field=field, value=value, status=status)


class TestHaversine(unittest.TestCase):
    def test_zero_distance_for_identical_points(self) -> None:
        self.assertEqual(_haversine_km(35.0, 129.0, 35.0, 129.0), 0.0)

    def test_known_distance_one_degree_latitude(self) -> None:
        # 1 degree of latitude is ~111 km everywhere on Earth.
        distance = _haversine_km(35.0, 129.0, 36.0, 129.0)
        self.assertAlmostEqual(distance, 111.0, delta=1.0)


class TestFilterByScore(unittest.TestCase):
    def test_excludes_below_min_rating_and_review_count(self) -> None:
        places = [
            _place("low_rating", 35.0, 129.0, rating=3.0, review_count=100),
            _place("low_reviews", 35.0, 129.0, rating=4.5, review_count=5),
            _place("ok", 35.0, 129.0, rating=4.0, review_count=50),
        ]

        result = filter_by_score(places, min_rating=3.5, min_review_count=10)

        self.assertEqual([sp.place.place_id for sp in result], ["ok"])

    def test_excludes_places_with_null_rating_or_review_count(self) -> None:
        places = [
            _place("no_rating", 35.0, 129.0, rating=None, review_count=100),
            _place("no_reviews", 35.0, 129.0, rating=4.5, review_count=None),
        ]

        result = filter_by_score(places)

        self.assertEqual(result, [])

    def test_score_formula_matches_weighted_sum(self) -> None:
        place = _place("p1", 35.0, 129.0, rating=4.0, review_count=100)

        result = filter_by_score(
            [place], w_rating=2.0, w_review_count=3.0, w_distance=1.0, min_rating=0, min_review_count=0
        )

        expected = 2.0 * 4.0 + 3.0 * math.log(100)  # no reference places -> distance term is 0
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].score, expected)
        self.assertIsNone(result[0].distance_km)

    def test_penalizes_candidates_far_from_reference_places(self) -> None:
        reference = [_place("ref", 35.0, 129.0, rating=4.0, review_count=100)]
        near = _place("near", 35.001, 129.0, rating=4.0, review_count=100)
        far = _place("far", 40.0, 135.0, rating=4.0, review_count=100)

        result = filter_by_score([near, far], reference_places=reference)

        by_id = {sp.place.place_id: sp for sp in result}
        self.assertGreater(by_id["near"].score, by_id["far"].score)
        self.assertLess(by_id["near"].distance_km, by_id["far"].distance_km)

    def test_ignores_self_as_reference_place(self) -> None:
        place = _place("p1", 35.0, 129.0)

        result = filter_by_score([place], reference_places=[place])

        self.assertIsNone(result[0].distance_km)

    def test_sorted_descending_and_top_n_applied(self) -> None:
        places = [
            _place("mid", 35.0, 129.0, rating=4.0, review_count=50),
            _place("best", 35.0, 129.0, rating=5.0, review_count=500),
            _place("worst", 35.0, 129.0, rating=3.6, review_count=11),
        ]

        result = filter_by_score(places, top_n=2)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].place.place_id, "best")
        self.assertGreaterEqual(result[0].score, result[1].score)


class TestPlaceSelector(unittest.TestCase):
    def test_returns_empty_without_calling_llm_when_no_candidates(self) -> None:
        fake_client = MagicMock()
        selector = PlaceSelector(client=fake_client, max_retries=1, retry_delay_seconds=0)

        result = selector.select([], [_slot(SlotField.wishlist, "회 맛집")])

        self.assertEqual(result, [])
        fake_client.chat.completions.create.assert_not_called()

    def test_parses_valid_selection(self) -> None:
        candidates = [ScoredPlace(place=_place("p1", 35.0, 129.0), score=5.0, distance_km=None)]
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response(
            {"selections": [{"place_id": "p1", "selection_reason": "회 맛집을 찾던 대화와 일치합니다."}]}
        )
        selector = PlaceSelector(client=fake_client, max_retries=1, retry_delay_seconds=0)

        result = selector.select(candidates, [_slot(SlotField.wishlist, "회 맛집")])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].place_id, "p1")

    def test_filters_out_hallucinated_place_ids(self) -> None:
        candidates = [ScoredPlace(place=_place("p1", 35.0, 129.0), score=5.0, distance_km=None)]
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response(
            {
                "selections": [
                    {"place_id": "p1", "selection_reason": "실제 후보"},
                    {"place_id": "does_not_exist", "selection_reason": "지어낸 장소"},
                ]
            }
        )
        selector = PlaceSelector(client=fake_client, max_retries=1, retry_delay_seconds=0)

        result = selector.select(candidates, [])

        self.assertEqual([s.place_id for s in result], ["p1"])

    def test_retries_then_raises_on_persistent_invalid_json(self) -> None:
        candidates = [ScoredPlace(place=_place("p1", 35.0, 129.0), score=5.0, distance_km=None)]
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = raw_text_response("not valid json")
        selector = PlaceSelector(client=fake_client, max_retries=2, retry_delay_seconds=0)

        with self.assertRaises(PlaceSelectionError):
            selector.select(candidates, [])

        self.assertEqual(fake_client.chat.completions.create.call_count, 3)

    def test_refusal_is_treated_as_a_retryable_failure(self) -> None:
        candidates = [ScoredPlace(place=_place("p1", 35.0, 129.0), score=5.0, distance_km=None)]
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = refusal_response()
        selector = PlaceSelector(client=fake_client, max_retries=1, retry_delay_seconds=0)

        with self.assertRaises(PlaceSelectionError):
            selector.select(candidates, [])

        self.assertEqual(fake_client.chat.completions.create.call_count, 2)


if __name__ == "__main__":
    unittest.main()
