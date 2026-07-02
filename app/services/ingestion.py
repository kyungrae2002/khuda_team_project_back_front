"""Ingests a KakaoTalk export: parses it, persists messages, extracts travel
slots via Claude, and persists them. Keeps app/api/sessions.py's upload route
thin."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.slot import Slot
from app.models.travel_session import TravelSession
from app.services.kakao_parser import parse
from app.services.slot_extractor import SlotExtractionResult, slot_extractor
from app.services.slot_service import SlotService


@dataclass
class IngestionResult:
    session: TravelSession
    slots: list[Slot]
    raw_unparsed_count: int


def ingest_conversation(db: Session, title: str, file_content: str) -> IngestionResult:
    parse_result = parse(file_content)

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
