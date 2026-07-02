import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.slot import SlotField, SlotStatus
from app.services.query_builder import (
    QueryBuildError,
    QueryBuilder,
    _find_missing_critical_slots,
)
from tests.openai_fakes import raw_text_response, text_response


def _slot(field: SlotField, value: str, status: SlotStatus = SlotStatus.confirmed):
    return SimpleNamespace(field=field, value=value, status=status)


class TestFindMissingCriticalSlots(unittest.TestCase):
    def test_destination_missing_entirely(self) -> None:
        slots = [_slot(SlotField.wishlist, "회 맛집")]
        self.assertEqual(_find_missing_critical_slots(slots), [SlotField.destination])

    def test_destination_undecided_counts_as_missing(self) -> None:
        slots = [_slot(SlotField.destination, "부산", status=SlotStatus.undecided)]
        self.assertEqual(_find_missing_critical_slots(slots), [SlotField.destination])

    def test_destination_confirmed_is_not_missing(self) -> None:
        slots = [_slot(SlotField.destination, "부산")]
        self.assertEqual(_find_missing_critical_slots(slots), [])


class TestQueryBuilder(unittest.TestCase):
    def test_short_circuits_without_calling_llm_when_destination_missing(self) -> None:
        fake_client = MagicMock()
        builder = QueryBuilder(client=fake_client, max_retries=1, retry_delay_seconds=0)

        result = builder.build([_slot(SlotField.wishlist, "회 맛집")])

        self.assertEqual(result.missing_critical_slots, [SlotField.destination])
        self.assertEqual(result.queries, [])
        fake_client.chat.completions.create.assert_not_called()

    def test_builds_queries_from_confirmed_destination_and_wishlist(self) -> None:
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response(
            {
                "queries": [
                    {"query_text": "부산 회 맛집", "search_type": "text", "category": "restaurant"}
                ]
            }
        )
        builder = QueryBuilder(client=fake_client, max_retries=1, retry_delay_seconds=0)

        result = builder.build(
            [_slot(SlotField.destination, "부산"), _slot(SlotField.wishlist, "회 맛집")]
        )

        self.assertEqual(result.missing_critical_slots, [])
        self.assertEqual(len(result.queries), 1)
        self.assertEqual(result.queries[0].query_text, "부산 회 맛집")
        self.assertEqual(result.queries[0].category.value, "restaurant")

    def test_ignores_irrelevant_confirmed_fields_like_budget(self) -> None:
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response(
            {"queries": [{"query_text": "부산", "search_type": "text", "category": "tourist_attraction"}]}
        )
        builder = QueryBuilder(client=fake_client, max_retries=1, retry_delay_seconds=0)

        builder.build([_slot(SlotField.destination, "부산"), _slot(SlotField.budget, "50만원")])

        sent_messages = fake_client.chat.completions.create.call_args.kwargs["messages"]
        user_prompt = next(m["content"] for m in sent_messages if m["role"] == "user")
        self.assertIn("destination: 부산", user_prompt)
        self.assertNotIn("budget", user_prompt)

    def test_retries_then_raises_on_persistent_invalid_json(self) -> None:
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = raw_text_response("not valid json")
        builder = QueryBuilder(client=fake_client, max_retries=2, retry_delay_seconds=0)

        with self.assertRaises(QueryBuildError):
            builder.build([_slot(SlotField.destination, "부산")])

        self.assertEqual(fake_client.chat.completions.create.call_count, 3)


if __name__ == "__main__":
    unittest.main()
