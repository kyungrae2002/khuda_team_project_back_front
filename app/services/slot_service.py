from sqlalchemy.orm import Session

from app.models.slot import Slot, SlotField, SlotStatus


class SlotValidationError(ValueError):
    """Raised when a Slot fails domain validation before being persisted."""


class SlotService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_slot(
        self,
        *,
        session_id: int,
        field: SlotField,
        value: str,
        status: SlotStatus,
        evidence_message_ids: list[int],
        confidence: float,
    ) -> Slot:
        self._validate_evidence(evidence_message_ids)

        slot = Slot(
            session_id=session_id,
            field=field,
            value=value,
            status=status,
            evidence_message_ids=evidence_message_ids,
            confidence=confidence,
        )
        self._db.add(slot)
        self._db.flush()
        return slot

    def update_evidence(self, slot: Slot, evidence_message_ids: list[int]) -> Slot:
        self._validate_evidence(evidence_message_ids)
        slot.evidence_message_ids = evidence_message_ids
        self._db.flush()
        return slot

    @staticmethod
    def _validate_evidence(evidence_message_ids: list[int]) -> None:
        if not evidence_message_ids:
            raise SlotValidationError(
                "evidence_message_ids must reference at least one ChatMessage; "
                "a Slot cannot be created or updated without supporting evidence."
            )
