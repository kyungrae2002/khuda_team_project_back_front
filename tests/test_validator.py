import unittest
from datetime import date, datetime, time

from app.models.itinerary_item import ItineraryItem, ReservationNeeded
from app.models.place import Place
from app.services.validator import check_business_hours, check_buffer, check_round_trip


def _place(place_id: int, lat: float, lng: float, opening_hours: dict | None = None) -> Place:
    return Place(
        id=place_id,
        place_id=f"ext-{place_id}",
        name=f"place-{place_id}",
        lat=lat,
        lng=lng,
        opening_hours=opening_hours,
    )


def _item(place_id: int, day_index: int, order_in_day: int, arrival: datetime, duration: int = 60) -> ItineraryItem:
    return ItineraryItem(
        place_id=place_id,
        day_index=day_index,
        order_in_day=order_in_day,
        arrival_time=arrival,
        duration_minutes=duration,
        reservation_needed=ReservationNeeded.unnecessary,
    )


class TestCheckRoundTrip(unittest.TestCase):
    def test_detects_crossing_path(self) -> None:
        places = {
            1: _place(1, lat=0.0, lng=0.0),
            2: _place(2, lat=2.0, lng=2.0),
            3: _place(3, lat=2.0, lng=0.0),
            4: _place(4, lat=0.0, lng=2.0),
        }
        base = datetime(2025, 6, 23, 9, 0)
        itinerary = [
            _item(1, 0, 0, base),
            _item(2, 0, 1, base.replace(hour=10)),
            _item(3, 0, 2, base.replace(hour=11)),
            _item(4, 0, 3, base.replace(hour=12)),
        ]

        violations = check_round_trip(itinerary, places)

        self.assertTrue(any(v.type == "round_trip" for v in violations))

    def test_no_violation_for_straight_path(self) -> None:
        places = {
            1: _place(1, lat=0.0, lng=0.0),
            2: _place(2, lat=0.0, lng=1.0),
            3: _place(3, lat=0.0, lng=2.0),
            4: _place(4, lat=0.0, lng=3.0),
        }
        base = datetime(2025, 6, 23, 9, 0)
        itinerary = [
            _item(1, 0, 0, base),
            _item(2, 0, 1, base.replace(hour=10)),
            _item(3, 0, 2, base.replace(hour=11)),
            _item(4, 0, 3, base.replace(hour=12)),
        ]

        violations = check_round_trip(itinerary, places)

        self.assertEqual(violations, [])


class TestCheckBusinessHours(unittest.TestCase):
    def test_flags_arrival_outside_hours(self) -> None:
        day_date = date(2025, 6, 23)
        google_weekday = (day_date.weekday() + 1) % 7
        place = _place(
            1,
            lat=0.0,
            lng=0.0,
            opening_hours={
                "periods": [
                    {
                        "open": {"day": google_weekday, "hour": 9, "minute": 0},
                        "close": {"day": google_weekday, "hour": 18, "minute": 0},
                    }
                ]
            },
        )
        itinerary = [_item(1, 0, 0, datetime(2025, 6, 23, 20, 0))]

        violations = check_business_hours(itinerary, {1: place})

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, "business_hours")

    def test_no_violation_within_hours(self) -> None:
        day_date = date(2025, 6, 23)
        google_weekday = (day_date.weekday() + 1) % 7
        place = _place(
            1,
            lat=0.0,
            lng=0.0,
            opening_hours={
                "periods": [
                    {
                        "open": {"day": google_weekday, "hour": 9, "minute": 0},
                        "close": {"day": google_weekday, "hour": 18, "minute": 0},
                    }
                ]
            },
        )
        itinerary = [_item(1, 0, 0, datetime(2025, 6, 23, 10, 0))]

        self.assertEqual(check_business_hours(itinerary, {1: place}), [])

    def test_no_violation_when_hours_unknown(self) -> None:
        place = _place(1, lat=0.0, lng=0.0, opening_hours=None)
        itinerary = [_item(1, 0, 0, datetime(2025, 6, 23, 23, 0))]

        self.assertEqual(check_business_hours(itinerary, {1: place}), [])


class TestCheckBuffer(unittest.TestCase):
    def test_flags_insufficient_buffer(self) -> None:
        places = {1: _place(1, 0.0, 0.0), 2: _place(2, 0.0, 0.0)}  # same coords -> 0 travel time
        itinerary = [
            _item(1, 0, 0, datetime(2025, 6, 23, 9, 0), duration=60),  # departs 10:00
            _item(2, 0, 1, datetime(2025, 6, 23, 10, 5)),  # only 5 min buffer
        ]

        violations = check_buffer(itinerary, places, min_buffer_minutes=15)

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, "buffer")

    def test_no_violation_with_sufficient_buffer(self) -> None:
        places = {1: _place(1, 0.0, 0.0), 2: _place(2, 0.0, 0.0)}
        itinerary = [
            _item(1, 0, 0, datetime(2025, 6, 23, 9, 0), duration=60),  # departs 10:00
            _item(2, 0, 1, datetime(2025, 6, 23, 10, 30)),  # 30 min buffer
        ]

        self.assertEqual(check_buffer(itinerary, places, min_buffer_minutes=15), [])


if __name__ == "__main__":
    unittest.main()
