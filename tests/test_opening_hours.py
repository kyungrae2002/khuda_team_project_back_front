import unittest
from datetime import date, time

from app.models.place import Place
from app.services.opening_hours import get_opening_period


def _place_with_hours(opening_hours: dict | None) -> Place:
    return Place(id=1, place_id="p1", name="test", lat=35.0, lng=129.0, opening_hours=opening_hours)


class TestGetOpeningPeriod(unittest.TestCase):
    def test_returns_none_when_no_opening_hours(self) -> None:
        place = _place_with_hours(None)
        self.assertIsNone(get_opening_period(place, date(2025, 6, 23)))

    def test_returns_none_when_no_periods_key(self) -> None:
        place = _place_with_hours({"openNow": True})
        self.assertIsNone(get_opening_period(place, date(2025, 6, 23)))

    def test_matches_correct_weekday(self) -> None:
        day_date = date(2025, 6, 23)
        google_weekday = (day_date.weekday() + 1) % 7
        place = _place_with_hours(
            {
                "periods": [
                    {
                        "open": {"day": google_weekday, "hour": 9, "minute": 30},
                        "close": {"day": google_weekday, "hour": 21, "minute": 0},
                    }
                ]
            }
        )
        self.assertEqual(get_opening_period(place, day_date), (time(9, 30), time(21, 0)))

    def test_returns_none_when_no_period_matches_weekday(self) -> None:
        day_date = date(2025, 6, 23)
        wrong_weekday = ((day_date.weekday() + 1) % 7 + 1) % 7
        place = _place_with_hours(
            {
                "periods": [
                    {
                        "open": {"day": wrong_weekday, "hour": 9, "minute": 0},
                        "close": {"day": wrong_weekday, "hour": 21, "minute": 0},
                    }
                ]
            }
        )
        self.assertIsNone(get_opening_period(place, day_date))

    def test_overnight_period_falls_back_to_end_of_day(self) -> None:
        day_date = date(2025, 6, 23)
        google_weekday = (day_date.weekday() + 1) % 7
        next_weekday = (google_weekday + 1) % 7
        place = _place_with_hours(
            {
                "periods": [
                    {
                        "open": {"day": google_weekday, "hour": 22, "minute": 0},
                        "close": {"day": next_weekday, "hour": 2, "minute": 0},
                    }
                ]
            }
        )
        self.assertEqual(get_opening_period(place, day_date), (time(22, 0), time(23, 59)))


if __name__ == "__main__":
    unittest.main()
