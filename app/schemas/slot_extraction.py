from pydantic import BaseModel, ConfigDict, field_validator

from app.models.slot import SlotField, SlotStatus


class ExtractedSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: SlotField
    value: str
    status: SlotStatus
    evidence_message_ids: list[int]
    confidence: float

    @field_validator("evidence_message_ids")
    @classmethod
    def _evidence_must_not_be_empty(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("evidence_message_ids must not be empty")
        return value

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return value


class SlotExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slots: list[ExtractedSlot]
