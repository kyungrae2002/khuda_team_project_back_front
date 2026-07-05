import json
import unittest
from unittest.mock import MagicMock, patch

from app.schemas.slot_extraction import ExtractedSlot, SlotExtractionResult
from app.services.ingestion import _parse_upload, ingest_conversation


def _fake_extraction() -> SlotExtractionResult:
    return SlotExtractionResult(
        slots=[
            ExtractedSlot(
                field="destination",
                value="제주",
                status="confirmed",
                evidence_message_ids=[0],
                confidence=0.9,
            )
        ]
    )


class TestParseUploadDispatch(unittest.TestCase):
    def test_raw_kakao_export_is_routed_to_regex_parser(self) -> None:
        content = (
            "--------------- 2025년 6월 20일 ---------------\n"
            "2025년 6월 20일 오후 3:41, 김주연 : 이번엔 부산 어때??\n"
        )

        result = _parse_upload(content)

        self.assertEqual(len(result.messages), 1)
        self.assertEqual(result.messages[0].sender, "김주연")

    def test_json_payload_is_routed_to_json_parser(self) -> None:
        content = json.dumps(
            {
                "messages": [
                    {
                        "sender": "민지",
                        "timestamp": "2026-06-20T09:15:00",
                        "message": "제주도 가자",
                    }
                ]
            }
        )

        result = _parse_upload(content)

        self.assertEqual(len(result.messages), 1)
        self.assertEqual(result.messages[0].sender, "민지")
        self.assertEqual(result.raw_unparsed, [])


class TestIngestConversation(unittest.TestCase):
    def test_json_payload_produces_populated_slots_not_raw_unparsed(self) -> None:
        content = json.dumps(
            {
                "messages": [
                    {
                        "sender": "민지",
                        "timestamp": "2026-06-20T09:15:00",
                        "message": "제주도로 3박 4일 가자",
                    },
                    {
                        "sender": "수현",
                        "timestamp": "2026-06-20T09:16:00",
                        "message": "좋아! 예산은 1인당 50만원 정도로",
                    },
                ]
            }
        )
        db = MagicMock()

        with patch("app.services.ingestion.slot_extractor") as fake_extractor:
            fake_extractor.extract.return_value = _fake_extraction()
            result = ingest_conversation(db, title="테스트 여행", file_content=content)

        self.assertEqual(result.raw_unparsed_count, 0)
        self.assertEqual(len(result.slots), 1)
        self.assertEqual(result.slots[0].value, "제주")
        fake_extractor.extract.assert_called_once()
        (extracted_messages,), _ = fake_extractor.extract.call_args
        self.assertEqual(len(extracted_messages), 2)

    def test_raw_kakao_export_still_ingests_via_regex_parser(self) -> None:
        content = (
            "--------------- 2025년 6월 20일 ---------------\n"
            "2025년 6월 20일 오후 3:41, 김주연 : 이번엔 부산 어때??\n"
            "2025년 6월 20일 오후 3:42, 강경래 : 좋지, 예산은 얼마로 할까\n"
        )
        db = MagicMock()

        with patch("app.services.ingestion.slot_extractor") as fake_extractor:
            fake_extractor.extract.return_value = _fake_extraction()
            result = ingest_conversation(db, title="테스트 여행", file_content=content)

        self.assertEqual(result.raw_unparsed_count, 0)
        self.assertEqual(len(result.slots), 1)


if __name__ == "__main__":
    unittest.main()
