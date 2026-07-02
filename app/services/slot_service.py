from typing import Sequence

from sqlalchemy.orm import Session

from app.models.slot import Slot, SlotField, SlotStatus

# destination/date/budget/headcount/transport are conceptually one value per
# trip; constraint/wishlist are naturally multi-valued (several confirmed
# rows for the same field is normal, not a conflict).
_SINGULAR_FIELDS: tuple[SlotField, ...] = (
    SlotField.destination,
    SlotField.date,
    SlotField.budget,
    SlotField.headcount,
    SlotField.transport,
)
_LIST_FIELDS: tuple[SlotField, ...] = (SlotField.constraint, SlotField.wishlist)


class SlotValidationError(ValueError):
    """Raised when a Slot fails domain validation before being persisted."""


def build_slot_summary(slots: Sequence[Slot]) -> dict[str, object]:
    """Per-field snapshot for the frontend clarification flow: only
    `confirmed` values count as "obtained from the chat" — undecided/
    conflict/missing-entirely all collapse to null so the frontend can
    prompt the user directly for exactly those fields."""
    summary: dict[str, object] = {}
    for field in _SINGULAR_FIELDS:
        confirmed = [s.value for s in slots if s.field == field and s.status == SlotStatus.confirmed]
        summary[field.value] = confirmed[0] if confirmed else None
    for field in _LIST_FIELDS:
        confirmed = [s.value for s in slots if s.field == field and s.status == SlotStatus.confirmed]
        summary[field.value] = confirmed if confirmed else None
    return summary


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

    def create_user_provided_slot(self, *, session_id: int, field: SlotField, value: str) -> Slot:
        """A slot value the user typed directly in the frontend clarification
        flow — not inferred from chat, so no ChatMessage evidence exists.
        Always confirmed at full confidence: it supersedes any chat-derived
        value for the same field once _best_slot()/build_slot_summary() see
        it (confirmed always wins over conflict/undecided)."""
        slot = Slot(
            session_id=session_id,
            field=field,
            value=value,
            status=SlotStatus.confirmed,
            evidence_message_ids=[],
            confidence=1.0,
        )
        self._db.add(slot)
        self._db.flush()
        return slot

    @staticmethod
    def _validate_evidence(evidence_message_ids: list[int]) -> None:
        if not evidence_message_ids:
            raise SlotValidationError(
                "evidence_message_ids must reference at least one ChatMessage; "
                "a Slot cannot be created or updated without supporting evidence."
            )
