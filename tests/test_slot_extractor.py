import unittest
from datetime import datetime
from unittest.mock import MagicMock

from app.models.chat_message import ChatMessage
from app.services.slot_extractor import (
    SlotExtractionError,
    SlotExtractor,
    _format_conversation,
)
from tests.openai_fakes import raw_text_response, refusal_response, text_response


def _sample_messages() -> list[ChatMessage]:
    return [
        ChatMessage(
            sender="김주연",
            timestamp=datetime(2025, 6, 20, 15, 41),
            text="이번엔 부산 어때??",
            order_index=0,
            is_media=False,
        ),
        ChatMessage(
            sender="강경래",
            timestamp=datetime(2025, 6, 20, 15, 42),
            text="사진",
            order_index=1,
            is_media=True,
        ),
        ChatMessage(
            sender="강경래",
            timestamp=datetime(2025, 6, 20, 15, 43),
            text="ㅋㅋㅋ 좋지",
            order_index=2,
            is_media=False,
        ),
    ]


class TestFormatConversation(unittest.TestCase):
    def test_excludes_media_messages_and_includes_order_index(self) -> None:
        formatted = _format_conversation(_sample_messages())

        self.assertIn("[0] 김주연: 이번엔 부산 어때??", formatted)
        self.assertIn("[2] 강경래: ㅋㅋㅋ 좋지", formatted)
        self.assertNotIn("[1]", formatted)


class TestSlotExtractorRetry(unittest.TestCase):
    def test_returns_validated_result_on_first_success(self) -> None:
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response(
            {
                "slots": [
                    {
                        "field": "destination",
                        "value": "부산",
                        "status": "confirmed",
                        "evidence_message_ids": [0],
                        "confidence": 0.9,
                    }
                ]
            }
        )
        extractor = SlotExtractor(client=fake_client, max_retries=2, retry_delay_seconds=0)

        result = extractor.extract(_sample_messages())

        self.assertEqual(fake_client.chat.completions.create.call_count, 1)
        self.assertEqual(len(result.slots), 1)
        self.assertEqual(result.slots[0].field.value, "destination")
        self.assertEqual(result.slots[0].evidence_message_ids, [0])

    def test_retries_up_to_max_retries_then_raises(self) -> None:
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = raw_text_response("not valid json")
        extractor = SlotExtractor(client=fake_client, max_retries=2, retry_delay_seconds=0)

        with self.assertRaises(SlotExtractionError):
            extractor.extract(_sample_messages())

        self.assertEqual(fake_client.chat.completions.create.call_count, 3)

    def test_refusal_is_treated_as_a_retryable_failure(self) -> None:
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = refusal_response()
        extractor = SlotExtractor(client=fake_client, max_retries=1, retry_delay_seconds=0)

        with self.assertRaises(SlotExtractionError):
            extractor.extract(_sample_messages())

        self.assertEqual(fake_client.chat.completions.create.call_count, 2)

    def test_empty_evidence_message_ids_fails_validation_and_retries(self) -> None:
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = text_response(
            {
                "slots": [
                    {
                        "field": "destination",
                        "value": "부산",
                        "status": "confirmed",
                        "evidence_message_ids": [],
                        "confidence": 0.9,
                    }
                ]
            }
        )
        extractor = SlotExtractor(client=fake_client, max_retries=1, retry_delay_seconds=0)

        with self.assertRaises(SlotExtractionError):
            extractor.extract(_sample_messages())

        self.assertEqual(fake_client.chat.completions.create.call_count, 2)


if __name__ == "__main__":
    unittest.main()
