import unittest
from datetime import datetime

from app.services.json_conversation_parser import ConversationJSONError, parse_payload


class TestJSONConversationParser(unittest.TestCase):
    def test_parses_basic_message_list(self) -> None:
        payload = {
            "messages": [
                {"sender": "민지", "timestamp": "2026-06-20T09:15:00", "message": "제주 가자"},
                {"sender": "수현", "timestamp": "2026-06-20T09:16:00", "message": "사진"},
            ]
        }

        result = parse_payload(payload)

        self.assertEqual(len(result.messages), 2)
        self.assertEqual(result.raw_unparsed, [])

        first, second = result.messages
        self.assertEqual(first.sender, "민지")
        self.assertEqual(first.text, "제주 가자")
        self.assertEqual(first.timestamp, datetime(2026, 6, 20, 9, 15, 0))
        self.assertEqual(first.order_index, 0)
        self.assertFalse(first.is_media)

        self.assertEqual(second.order_index, 1)
        self.assertTrue(second.is_media)

    def test_missing_messages_key_raises(self) -> None:
        with self.assertRaises(ConversationJSONError):
            parse_payload({"not_messages": []})

    def test_messages_not_a_list_raises(self) -> None:
        with self.assertRaises(ConversationJSONError):
            parse_payload({"messages": "not a list"})

    def test_missing_field_in_entry_raises(self) -> None:
        with self.assertRaises(ConversationJSONError):
            parse_payload({"messages": [{"sender": "민지", "message": "제주 가자"}]})

    def test_invalid_timestamp_raises(self) -> None:
        with self.assertRaises(ConversationJSONError):
            parse_payload(
                {
                    "messages": [
                        {"sender": "민지", "timestamp": "not-a-date", "message": "제주 가자"}
                    ]
                }
            )


if __name__ == "__main__":
    unittest.main()
