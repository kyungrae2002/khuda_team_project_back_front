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


class SlotSummaryOut(BaseModel):
    """Per-field snapshot for the frontend clarification flow: a field is
    only non-null if the chat parse produced a `confirmed` value for it —
    undecided/conflict/missing-entirely all come back as null so the
    frontend knows exactly which fields still need to be asked about
    directly."""

    destination: str | None = None
    date: str | None = None
    budget: str | None = None
    headcount: str | None = None
    transport: str | None = None
    constraint: list[str] | None = None
    wishlist: list[str] | None = None


class SlotFillRequest(BaseModel):
    """Frontend echoes SlotSummaryOut back with the previously-null fields
    filled in. Fields left null (or omitted) are left untouched."""

    destination: str | None = None
    date: str | None = None
    budget: str | None = None
    headcount: str | None = None
    transport: str | None = None
    constraint: list[str] | None = None
    wishlist: list[str] | None = None


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
