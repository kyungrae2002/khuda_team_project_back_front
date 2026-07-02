import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock

from app.models.itinerary_item import ItineraryItem, ReservationNeeded
from app.models.place import Place
from app.services.narrator import (
    ItineraryNarrative,
    ItineraryNarrator,
    NarrationError,
    _fallback_narrative,
    _format_time_korean,
    _time_period,
    export_json,
    export_markdown,
    narrate,
)
from tests.openai_fakes import raw_text_response, text_response


def _place(place_id: int, name: str) -> Place:
    return Place(id=place_id, place_id=f"ext-{place_id}", name=name, lat=0.0, lng=0.0)


def _item(
    place_id: int,
    day_index: int,
    order_in_day: int,
    arrival: datetime,
    reservation: ReservationNeeded = ReservationNeeded.unnecessary,
) -> ItineraryItem:
    return ItineraryItem(
        place_id=place_id,
        day_index=day_index,
        order_in_day=order_in_day,
        arrival_time=arrival,
        duration_minutes=60,
        reservation_needed=reservation,
    )


class TestTimeFormatting(unittest.TestCase):
    def test_time_period_boundaries(self) -> None:
        self.assertEqual(_time_period(datetime(2025, 1, 1, 9, 0).time()), "오전")
        self.assertEqual(_time_period(datetime(2025, 1, 1, 11, 59).time()), "오전")
        self.assertEqual(_time_period(datetime(2025, 1, 1, 12, 0).time()), "오후")
        self.assertEqual(_time_period(datetime(2025, 1, 1, 17, 59).time()), "오후")
        self.assertEqual(_time_period(datetime(2025, 1, 1, 18, 0).time()), "저녁")

    def test_format_time_korean(self) -> None:
        self.assertEqual(_format_time_korean(datetime(2025, 1, 1, 10, 0).time()), "10시")
        self.assertEqual(_format_time_korean(datetime(2025, 1, 1, 14, 30).time()), "14시 30분")


class TestNarratorPipeline(unittest.TestCase):
    def _sample_itinerary(self):
        places_by_id = {1: _place(1, "장소A"), 2: _place(2, "장소B")}
        itinerary = [
            _item(1, 0, 0, datetime(2025, 7, 1, 10, 0), ReservationNeeded.required),
            _item(2, 0, 1, datetime(2025, 7, 1, 14, 30), ReservationNeeded.recommended),
        ]
        selection_reasons = {1: "회 맛집을 원하는 대화와 일치", 2: "카페 휴식 요청에 부합"}
        return itinerary, places_by_id, selection_reasons

    def test_returns_empty_without_calling_llm_for_empty_itinerary(self) -> None:
        fake_client = MagicMock()
        narrator = ItineraryNarrator(client=fake_client, max_retries=1, retry_delay_seconds=0)

        result = narrator.narrate([], {}, {})

        self.assertEqual(result.days, [])
        fake_client.chat.completions.create.assert_not_called()

    def test_merges_llm_narrative_with_deterministic_facts(self) -> None:
        itinerary, places_by_id, selection_reasons = self._sample_itinerary()
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response(
            {"days": [{"day_index": 0, "narrative": "1일차: 오전 - 장소A(도착 10시) → 오후 - 장소B(도착 14시 30분)"}]}
        )
        narrator = ItineraryNarrator(client=fake_client, max_retries=1, retry_delay_seconds=0)

        result = narrator.narrate(itinerary, places_by_id, selection_reasons)

        self.assertEqual(len(result.days), 1)
        day = result.days[0]
        self.assertIn("장소A", day.narrative)
        self.assertEqual(len(day.items), 2)
        self.assertEqual(day.items[0].place_name, "장소A")
        self.assertEqual(day.items[0].reservation_badge, "필수")
        self.assertEqual(day.items[0].selection_reason, "회 맛집을 원하는 대화와 일치")
        self.assertEqual(day.items[1].reservation_badge, "권장")

    def test_falls_back_to_deterministic_narrative_when_day_missing_from_llm(self) -> None:
        itinerary, places_by_id, selection_reasons = self._sample_itinerary()
        # LLM response omits day_index 0 entirely.
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response({"days": []})
        narrator = ItineraryNarrator(client=fake_client, max_retries=1, retry_delay_seconds=0)

        result = narrator.narrate(itinerary, places_by_id, selection_reasons)

        self.assertEqual(len(result.days), 1)
        self.assertIn("장소A", result.days[0].narrative)
        self.assertIn("장소B", result.days[0].narrative)
        self.assertIn("→", result.days[0].narrative)

    def test_ignores_hallucinated_day_index(self) -> None:
        itinerary, places_by_id, selection_reasons = self._sample_itinerary()
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response(
            {
                "days": [
                    {"day_index": 0, "narrative": "실제 1일차 서사"},
                    {"day_index": 99, "narrative": "존재하지 않는 날짜에 대한 지어낸 서사"},
                ]
            }
        )
        narrator = ItineraryNarrator(client=fake_client, max_retries=1, retry_delay_seconds=0)

        result = narrator.narrate(itinerary, places_by_id, selection_reasons)

        self.assertEqual(len(result.days), 1)
        self.assertEqual(result.days[0].narrative, "실제 1일차 서사")

    def test_retries_then_raises_on_persistent_invalid_json(self) -> None:
        itinerary, places_by_id, selection_reasons = self._sample_itinerary()
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = raw_text_response("not valid json")
        narrator = ItineraryNarrator(client=fake_client, max_retries=2, retry_delay_seconds=0)

        with self.assertRaises(NarrationError):
            narrator.narrate(itinerary, places_by_id, selection_reasons)

        self.assertEqual(fake_client.chat.completions.create.call_count, 3)

    def test_module_level_narrate_delegates_to_singleton(self) -> None:
        # Just verifies the convenience function doesn't blow up on empty input
        # without needing a real OpenAI client.
        result = narrate([], {}, {})
        self.assertIsInstance(result, ItineraryNarrative)
        self.assertEqual(result.days, [])


class TestFallbackNarrative(unittest.TestCase):
    def test_matches_expected_arrow_chained_format(self) -> None:
        itinerary, places_by_id, selection_reasons = TestNarratorPipeline()._sample_itinerary()
        from app.services.narrator import _build_item_narrative

        items = [_build_item_narrative(it, places_by_id, selection_reasons) for it in itinerary]

        text = _fallback_narrative(items)

        self.assertEqual(text, "오전 - 장소A(도착 10시) → 오후 - 장소B(도착 14시 30분)")


class TestExporters(unittest.TestCase):
    def _sample_narrative(self) -> ItineraryNarrative:
        itinerary, places_by_id, selection_reasons = TestNarratorPipeline()._sample_itinerary()
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response(
            {"days": [{"day_index": 0, "narrative": "1일차: 오전 - 장소A → 오후 - 장소B"}]}
        )
        narrator = ItineraryNarrator(client=fake_client, max_retries=1, retry_delay_seconds=0)
        return narrator.narrate(itinerary, places_by_id, selection_reasons)

    def test_export_json_round_trips_all_facts(self) -> None:
        narrative = self._sample_narrative()

        payload = json.loads(export_json(narrative))

        self.assertEqual(len(payload["days"]), 1)
        day = payload["days"][0]
        self.assertEqual(day["day_index"], 0)
        self.assertEqual(len(day["items"]), 2)
        self.assertEqual(day["items"][0]["place_name"], "장소A")
        self.assertEqual(day["items"][0]["reservation_badge"], "필수")
        self.assertEqual(day["items"][0]["selection_reason"], "회 맛집을 원하는 대화와 일치")

    def test_export_markdown_includes_badges_and_reasons(self) -> None:
        narrative = self._sample_narrative()

        markdown = export_markdown(narrative)

        self.assertIn("## 1일차", markdown)
        self.assertIn("장소A", markdown)
        self.assertIn("[예약 필수]", markdown)
        self.assertIn("회 맛집을 원하는 대화와 일치", markdown)
        self.assertIn("[예약 권장]", markdown)


if __name__ == "__main__":
    unittest.main()
