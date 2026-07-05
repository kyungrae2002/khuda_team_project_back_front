"""Ingests a conversation upload: parses it, persists messages, extracts
travel slots via Claude, and persists them. Keeps app/api/sessions.py's
upload route thin.

Accepts two input shapes, detected by content:
- A raw KakaoTalk .txt export, handled by kakao_parser.parse.
- A structured JSON payload ({"messages": [...]}) produced by the frontend's
  chatbot flow, handled by json_conversation_parser.parse_payload.
"""

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.slot import Slot
from app.models.travel_session import TravelSession
from app.services.json_conversation_parser import parse_payload
from app.services.kakao_parser import ParseResult
from app.services.kakao_parser import parse as parse_kakao_export
from app.services.slot_extractor import SlotExtractionResult, slot_extractor
from app.services.slot_service import SlotService


@dataclass
class IngestionResult:
    session: TravelSession
    slots: list[Slot]
    raw_unparsed_count: int


def _parse_upload(file_content: str) -> ParseResult:
    try:
        payload = json.loads(file_content)
    except json.JSONDecodeError:
        return parse_kakao_export(file_content)
    return parse_payload(payload)


def ingest_conversation(db: Session, title: str, file_content: str) -> IngestionResult:
    parse_result = _parse_upload(file_content)

    session = TravelSession(title=title)
    db.add(session)
    db.flush()

    for message in parse_result.messages:
        message.session_id = session.id
        db.add(message)
    db.commit()

    extraction: SlotExtractionResult = slot_extractor.extract(parse_result.messages)

    slot_service = SlotService(db)
    persisted_slots = [
        slot_service.create_slot(
            session_id=session.id,
            field=extracted.field,
            value=extracted.value,
            status=extracted.status,
            evidence_message_ids=extracted.evidence_message_ids,
            confidence=extracted.confidence,
        )
        for extracted in extraction.slots
    ]
    db.commit()

    return IngestionResult(
        session=session,
        slots=persisted_slots,
        raw_unparsed_count=len(parse_result.raw_unparsed),
    )
