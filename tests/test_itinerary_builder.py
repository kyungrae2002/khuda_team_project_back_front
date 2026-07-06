import unittest
from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock

from app.models.itinerary_item import ItineraryItem, ReservationNeeded
from app.models.place import Place
from app.services.itinerary_builder import (
    _balance_clusters,
    _kmeans_cluster,
    _nearest_neighbor_order,
    build_route,
    critique_and_fix,
)
from app.services.validator import check_buffer, check_round_trip
from tests.openai_fakes import text_response


def _place(place_id: int, lat: float, lng: float, opening_hours: dict | None = None) -> Place:
    return Place(
        id=place_id,
        place_id=f"ext-{place_id}",
        name=f"place-{place_id}",
        lat=lat,
        lng=lng,
        opening_hours=opening_hours,
    )


def _make_item(
    place_id: int, day_index: int, order_in_day: int, arrival: datetime, duration: int = 60
) -> ItineraryItem:
    return ItineraryItem(
        place_id=place_id,
        day_index=day_index,
        order_in_day=order_in_day,
        arrival_time=arrival,
        duration_minutes=duration,
        reservation_needed=ReservationNeeded.unnecessary,
    )


class TestKMeansCluster(unittest.TestCase):
    def test_produces_requested_cluster_count(self) -> None:
        places = [_place(i, lat=float(i), lng=0.0) for i in range(1, 7)]

        clusters = _kmeans_cluster(places, k=3)

        self.assertEqual(len(clusters), 3)
        self.assertEqual(sum(len(c) for c in clusters), 6)

    def test_caps_k_at_place_count(self) -> None:
        places = [_place(1, 0.0, 0.0), _place(2, 0.0, 1.0)]

        clusters = _kmeans_cluster(places, k=5)

        self.assertEqual(len(clusters), 2)


class TestBalanceClusters(unittest.TestCase):
    def test_evens_out_a_lopsided_split(self) -> None:
        # Regression test: geography-only kmeans can leave one day with 2
        # places and another with 6 purely by happenstance, starving the
        # thin day of enough stops to reach evening.
        thin = [_place(1, 0.0, 0.0), _place(2, 0.0, 0.1)]
        rich = [_place(i, 10.0, 10.0 + i * 0.01) for i in range(3, 9)]

        balanced = _balance_clusters([thin, rich])

        sizes = sorted(len(c) for c in balanced)
        self.assertEqual(sum(sizes), 8)
        self.assertLessEqual(sizes[-1] - sizes[0], 1)

    def test_leaves_already_balanced_clusters_untouched(self) -> None:
        a = [_place(1, 0.0, 0.0), _place(2, 0.0, 0.1)]
        b = [_place(3, 10.0, 10.0), _place(4, 10.0, 10.1)]

        balanced = _balance_clusters([a, b])

        self.assertEqual({p.id for p in balanced[0]}, {1, 2})
        self.assertEqual({p.id for p in balanced[1]}, {3, 4})

    def test_single_cluster_is_a_no_op(self) -> None:
        only = [_place(1, 0.0, 0.0)]

        balanced = _balance_clusters([only])

        self.assertEqual(len(balanced), 1)
        self.assertEqual(len(balanced[0]), 1)

    def test_handles_an_initially_empty_cluster(self) -> None:
        empty: list[Place] = []
        rich = [_place(i, 0.0, float(i)) for i in range(1, 5)]

        balanced = _balance_clusters([empty, rich])

        sizes = sorted(len(c) for c in balanced)
        self.assertEqual(sum(sizes), 4)
        self.assertLessEqual(sizes[-1] - sizes[0], 1)


class TestNearestNeighborOrder(unittest.TestCase):
    def test_visits_closest_unvisited_place_next(self) -> None:
        start = _place(1, 0.0, 0.0)
        near = _place(2, 0.0, 1.0)
        far = _place(3, 0.0, 10.0)

        ordered = _nearest_neighbor_order([start, far, near])

        self.assertEqual([p.id for p in ordered], [1, 2, 3])


class TestBuildRoute(unittest.TestCase):
    def test_assigns_day_index_and_sequential_order(self) -> None:
        places = [_place(1, 0.0, 0.0), _place(2, 0.0, 0.1), _place(3, 50.0, 50.0)]

        items = build_route(places, days=2, start_date=date(2025, 6, 23))

        self.assertEqual(len(items), 3)
        day_indices = {item.day_index for item in items}
        self.assertTrue(day_indices.issubset({0, 1}))
        for day_index in day_indices:
            day_items = sorted(
                (i for i in items if i.day_index == day_index), key=lambda i: i.order_in_day
            )
            self.assertEqual([i.order_in_day for i in day_items], list(range(len(day_items))))

    def test_waits_until_opening_time_when_arriving_early(self) -> None:
        start_date = date(2025, 6, 23)
        google_weekday = (start_date.weekday() + 1) % 7
        place = _place(
            1,
            0.0,
            0.0,
            opening_hours={
                "periods": [
                    {
                        "open": {"day": google_weekday, "hour": 11, "minute": 0},
                        "close": {"day": google_weekday, "hour": 20, "minute": 0},
                    }
                ]
            },
        )

        items = build_route([place], days=1, start_date=start_date, day_start_time=time(9, 0))

        self.assertEqual(items[0].arrival_time.time(), time(11, 0))


class TestCritiqueAndFix(unittest.TestCase):
    def test_resolves_after_one_iteration(self) -> None:
        place1 = _place(1, 0.0, 0.0)
        place2 = _place(2, 0.0, 1.0)
        places_by_id = {1: place1, 2: place2}

        base = datetime(2025, 6, 23, 9, 0)
        itinerary = [
            _make_item(1, 0, 0, base, duration=60),
            _make_item(2, 0, 1, base + timedelta(minutes=61)),  # almost no buffer
        ]
        violations = check_buffer(itinerary, places_by_id)
        self.assertTrue(violations, "test setup should start with a real violation")

        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response(
            {
                "days": [{"day_index": 0, "place_ids": [1, 2]}],
                "reservations": [
                    {"place_id": 1, "reservation_needed": "unnecessary"},
                    {"place_id": 2, "reservation_needed": "recommended"},
                ],
            }
        )
        db = MagicMock()

        result = critique_and_fix(
            db,
            session_id=1,
            places_by_id=places_by_id,
            itinerary=itinerary,
            violations=violations,
            iteration=0,
            start_date=date(2025, 6, 23),
            client=fake_client,
            retry_delay_seconds=0,
        )

        self.assertEqual(result.violations, [])
        self.assertEqual(result.iterations_used, 1)
        by_place = {item.place_id: item for item in result.itinerary}
        self.assertEqual(by_place[2].reservation_needed.value, "recommended")
        self.assertEqual(db.add.call_count, 2)  # logged at iteration 0 and iteration 1

    def test_exhausts_max_iterations_and_returns_with_violations(self) -> None:
        places_by_id = {
            1: _place(1, 0.0, 0.0),
            2: _place(2, 2.0, 2.0),
            3: _place(3, 2.0, 0.0),
            4: _place(4, 0.0, 2.0),
        }
        base = datetime(2025, 6, 23, 9, 0)
        itinerary = [
            _make_item(place_id, 0, i, base.replace(hour=9 + i))
            for i, place_id in enumerate([1, 2, 3, 4])
        ]
        violations = check_round_trip(itinerary, places_by_id)
        self.assertTrue(violations, "test setup should start with a crossing path violation")

        # The mock LLM keeps proposing the exact same (still-crossing) order,
        # so the violation can never actually resolve.
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response(
            {"days": [{"day_index": 0, "place_ids": [1, 2, 3, 4]}], "reservations": []}
        )
        db = MagicMock()

        result = critique_and_fix(
            db,
            session_id=1,
            places_by_id=places_by_id,
            itinerary=itinerary,
            violations=violations,
            iteration=0,
            start_date=date(2025, 6, 23),
            client=fake_client,
            retry_delay_seconds=0,
        )

        self.assertEqual(result.iterations_used, 2)
        self.assertTrue(len(result.violations) > 0)
        self.assertEqual(fake_client.chat.completions.create.call_count, 2)
        self.assertEqual(db.add.call_count, 3)  # logged at iteration 0, 1, and 2


if __name__ == "__main__":
    unittest.main()
