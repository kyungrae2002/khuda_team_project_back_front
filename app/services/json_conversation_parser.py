"""Parser for the structured JSON conversation payload the frontend sends
once the chatbot flow finishes (an LLM-organized summary of the original
KakaoTalk export plus the chatbot Q&A), as an alternative to the raw
KakaoTalk .txt export handled by kakao_parser.py.

Expected shape:
{
  "messages": [
    {"sender": "민지", "timestamp": "2026-06-20T09:15:00", "message": "..."},
    ...
  ]
}

"timestamp" must be ISO 8601 (datetime.fromisoformat-compatible).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.chat_message import ChatMessage
from app.services.kakao_parser import ParseResult, _is_media_text


class ConversationJSONError(ValueError):
    """Raised when a JSON payload doesn't match the expected conversation schema."""


def parse_payload(payload: Any) -> ParseResult:
    if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
        raise ConversationJSONError('JSON 페이로드는 {"messages": [...]} 형식이어야 합니다.')

    result = ParseResult()
    for order_index, entry in enumerate(payload["messages"]):
        try:
            sender = entry["sender"]
            text = entry["message"]
            timestamp = datetime.fromisoformat(entry["timestamp"])
            if not isinstance(sender, str) or not isinstance(text, str):
                raise TypeError("sender와 message는 문자열이어야 합니다")
        except (KeyError, TypeError, ValueError) as exc:
            raise ConversationJSONError(
                f"{order_index}번째 메시지 형식이 올바르지 않습니다: {exc}"
            ) from exc

        result.messages.append(
            ChatMessage(
                sender=sender,
                timestamp=timestamp,
                text=text,
                order_index=order_index,
                is_media=_is_media_text(text),
            )
        )

    return result
