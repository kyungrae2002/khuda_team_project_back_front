from pydantic import BaseModel, ConfigDict

from app.models.slot import SlotField, SlotStatus


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field: SlotField
    value: str
    status: SlotStatus
    confidence: float
    evidence_message_ids: list[int]


class UploadResponse(BaseModel):
    session_id: int
    slots: list[SlotOut]
    raw_unparsed_count: int


class ItineraryRequest(BaseModel):
    days: int = 1


class ItemNarrativeOut(BaseModel):
    place_id: int
    place_name: str
    time_period: str
    arrival_time: str
    arrival_time_label: str
    reservation_badge: str
    selection_reason: str | None


class DayNarrativeOut(BaseModel):
    day_index: int
    narrative: str
    items: list[ItemNarrativeOut]


class ItineraryNarrativeOut(BaseModel):
    days: list[DayNarrativeOut]


class ViolationOut(BaseModel):
    type: str
    item_id: int
    description: str


class ItineraryResponse(BaseModel):
    narrative: ItineraryNarrativeOut
    iterations_used: int
    violations: list[ViolationOut]
