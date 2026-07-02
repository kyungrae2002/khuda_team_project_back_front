import unittest
from datetime import date
from unittest.mock import MagicMock

from app.services.date_resolver import DateResolutionError, DateResolver
from tests.openai_fakes import raw_text_response, text_response


class TestDateResolver(unittest.TestCase):
    def test_resolves_day_only_expression_to_iso_date(self) -> None:
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response(
            {"could_resolve": True, "resolved_date": "2025-06-21"}
        )
        resolver = DateResolver(client=fake_client, max_retries=1, retry_delay_seconds=0)

        result = resolver.resolve("21일", date(2025, 6, 20))

        self.assertEqual(result, date(2025, 6, 21))

    def test_unresolvable_expression_returns_none(self) -> None:
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response(
            {"could_resolve": False, "resolved_date": ""}
        )
        resolver = DateResolver(client=fake_client, max_retries=1, retry_delay_seconds=0)

        result = resolver.resolve("나중에 정하자", date(2025, 6, 20))

        self.assertIsNone(result)

    def test_malformed_resolved_date_returns_none(self) -> None:
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response(
            {"could_resolve": True, "resolved_date": "not-a-date"}
        )
        resolver = DateResolver(client=fake_client, max_retries=1, retry_delay_seconds=0)

        result = resolver.resolve("21일", date(2025, 6, 20))

        self.assertIsNone(result)

    def test_retries_then_raises_on_persistent_invalid_json(self) -> None:
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = raw_text_response("not valid json")
        resolver = DateResolver(client=fake_client, max_retries=2, retry_delay_seconds=0)

        with self.assertRaises(DateResolutionError):
            resolver.resolve("21일", date(2025, 6, 20))

        self.assertEqual(fake_client.chat.completions.create.call_count, 3)


if __name__ == "__main__":
    unittest.main()
