"""Parser for KakaoTalk PC chat export (.txt) files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.models.chat_message import ChatMessage

_DATE_HEADER_RE = re.compile(
    r"^-+\s*(?P<year>\d{4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일.*-+$"
)

# PC 카카오톡 내보내기: "2025년 6월 20일 오후 3:41, 이름 : 메시지" — 줄마다 날짜 포함.
_MESSAGE_RE = re.compile(
    r"^(?P<year>\d{4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일\s*"
    r"(?P<ampm>오전|오후)\s*(?P<hour>\d{1,2}):(?P<minute>\d{2}),\s*"
    r"(?P<sender>.+?)\s*:\s*(?P<text>.*)$"
)

# 모바일 대화 내보내기: "[이름] [오후 11:50] 메시지" — 날짜는 줄마다 없고 위쪽
# 날짜 구분선(_DATE_HEADER_RE)을 따라간다.
_BRACKET_MESSAGE_RE = re.compile(
    r"^\[(?P<sender>.+?)\]\s*\[(?P<ampm>오전|오후)\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})\]\s*"
    r"(?P<text>.*)$"
)

# A line that starts with "YYYY년" but fails _MESSAGE_RE is a corrupted
# message header, not free-form continuation text — route it to
# raw_unparsed instead of silently appending it to the previous message.
_LOOKS_LIKE_MESSAGE_RE = re.compile(r"^\d{4}\s*년")

_MEDIA_KEYWORDS = ("사진", "이모티콘")


@dataclass
class ParseResult:
    messages: list[ChatMessage] = field(default_factory=list)
    raw_unparsed: list[str] = field(default_factory=list)


def _hour_24(match: re.Match[str]) -> int:
    hour = int(match["hour"]) % 12
    if match["ampm"] == "오후":
        hour += 12
    return hour


def _to_timestamp(match: re.Match[str]) -> datetime:
    return datetime(
        int(match["year"]),
        int(match["month"]),
        int(match["day"]),
        _hour_24(match),
        int(match["minute"]),
    )


def _to_timestamp_for_date(date: tuple[int, int, int], match: re.Match[str]) -> datetime:
    year, month, day = date
    return datetime(year, month, day, _hour_24(match), int(match["minute"]))


def _is_media_text(text_value: str) -> bool:
    stripped = text_value.strip()
    return any(
        stripped == keyword or stripped.startswith(f"{keyword} ")
        for keyword in _MEDIA_KEYWORDS
    )


def parse(file_content: str) -> ParseResult:
    result = ParseResult()
    order_index = 0
    # Bracket-format messages don't carry a date themselves — they rely on
    # the most recent date-divider line. Falls back to this sentinel if a
    # bracket message somehow appears before any divider has been seen.
    current_date: tuple[int, int, int] = (1970, 1, 1)

    for line in file_content.splitlines():
        stripped = line.strip()

        if not stripped:
            continue

        date_header_match = _DATE_HEADER_RE.match(stripped)
        if date_header_match:
            current_date = (
                int(date_header_match["year"]),
                int(date_header_match["month"]),
                int(date_header_match["day"]),
            )
            continue

        match = _MESSAGE_RE.match(line)
        if match:
            text_value = match["text"]
            result.messages.append(
                ChatMessage(
                    sender=match["sender"],
                    timestamp=_to_timestamp(match),
                    text=text_value,
                    order_index=order_index,
                    is_media=_is_media_text(text_value),
                )
            )
            order_index += 1
            continue

        bracket_match = _BRACKET_MESSAGE_RE.match(line)
        if bracket_match:
            text_value = bracket_match["text"]
            result.messages.append(
                ChatMessage(
                    sender=bracket_match["sender"],
                    timestamp=_to_timestamp_for_date(current_date, bracket_match),
                    text=text_value,
                    order_index=order_index,
                    is_media=_is_media_text(text_value),
                )
            )
            order_index += 1
            continue

        if _LOOKS_LIKE_MESSAGE_RE.match(stripped):
            result.raw_unparsed.append(line)
            continue

        if result.messages:
            last = result.messages[-1]
            last.text = f"{last.text}\n{line}"
            continue

        result.raw_unparsed.append(line)

    return result
