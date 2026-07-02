import unittest
from datetime import datetime

from app.services.kakao_parser import parse


class TestKakaoParser(unittest.TestCase):
    def test_parses_basic_conversation(self) -> None:
        content = (
            "--------------- 2025년 6월 20일 ---------------\n"
            "2025년 6월 20일 오후 3:41, 김주연 : 이번엔 부산 어때??\n"
            "2025년 6월 20일 오후 3:42, 강경래 : ㅋㅋㅋ 좋지 근데 예산이...\n"
        )

        result = parse(content)

        self.assertEqual(len(result.messages), 2)
        self.assertEqual(result.raw_unparsed, [])

        first, second = result.messages
        self.assertEqual(first.sender, "김주연")
        self.assertEqual(first.text, "이번엔 부산 어때??")
        self.assertEqual(first.timestamp, datetime(2025, 6, 20, 15, 41))
        self.assertEqual(first.order_index, 0)
        self.assertFalse(first.is_media)

        self.assertEqual(second.sender, "강경래")
        self.assertEqual(second.text, "ㅋㅋㅋ 좋지 근데 예산이...")
        self.assertEqual(second.timestamp, datetime(2025, 6, 20, 15, 42))
        self.assertEqual(second.order_index, 1)
        self.assertFalse(second.is_media)

    def test_handles_media_multiline_and_unparsable_lines(self) -> None:
        content = (
            "--------------- 2025년 6월 20일 ---------------\n"
            "2025년 6월 20일 오후 3:43, 김주연 : 사진\n"
            "2025년 6월 20일 오후 3:44, 강경래 : 그건 그렇고\n"
            "숙소는 어디로 할까\n"
            "게스트하우스 좋아보이던데\n"
            "2025년 6월 20일 이상한 형식의 라인\n"
        )

        result = parse(content)

        self.assertEqual(len(result.messages), 2)
        media_message, multiline_message = result.messages

        self.assertTrue(media_message.is_media)
        self.assertEqual(media_message.text, "사진")
        self.assertEqual(media_message.order_index, 0)

        self.assertFalse(multiline_message.is_media)
        self.assertEqual(
            multiline_message.text,
            "그건 그렇고\n숙소는 어디로 할까\n게스트하우스 좋아보이던데",
        )
        self.assertEqual(multiline_message.order_index, 1)

        self.assertEqual(len(result.raw_unparsed), 1)
        self.assertIn("이상한 형식의 라인", result.raw_unparsed[0])

    def test_parses_bracket_format_conversation(self) -> None:
        content = (
            "--------------- 2025년 6월 20일 ---------------\n"
            "[김주연] [오후 3:41] 이번엔 부산 어때??\n"
            "[강경래] [오후 3:42] ㅋㅋㅋ 좋지 근데 예산이...\n"
            "[(알 수 없음)] [오후 3:43] 나도 찬성\n"
        )

        result = parse(content)

        self.assertEqual(len(result.messages), 3)
        self.assertEqual(result.raw_unparsed, [])

        first, second, third = result.messages
        self.assertEqual(first.sender, "김주연")
        self.assertEqual(first.text, "이번엔 부산 어때??")
        self.assertEqual(first.timestamp, datetime(2025, 6, 20, 15, 41))
        self.assertEqual(first.order_index, 0)

        self.assertEqual(second.sender, "강경래")
        self.assertEqual(second.timestamp, datetime(2025, 6, 20, 15, 42))

        self.assertEqual(third.sender, "(알 수 없음)")
        self.assertEqual(third.text, "나도 찬성")

    def test_bracket_format_multiline_continuation(self) -> None:
        content = (
            "--------------- 2025년 6월 20일 ---------------\n"
            "[강경래] [오후 11:54] 어디서 만날지 정해야하니\n"
            "추가로 생각해볼까\n"
        )

        result = parse(content)

        self.assertEqual(len(result.messages), 1)
        self.assertEqual(
            result.messages[0].text, "어디서 만날지 정해야하니\n추가로 생각해볼까"
        )


if __name__ == "__main__":
    unittest.main()
