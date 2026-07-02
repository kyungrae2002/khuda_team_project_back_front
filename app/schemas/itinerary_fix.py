from typing import Literal

from pydantic import BaseModel, ConfigDict


class DayPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_index: int
    place_ids: list[int]


class ReservationAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_id: int
    reservation_needed: Literal["required", "recommended", "unnecessary"]


class ItineraryFixSuggestion(BaseModel):
    """Shape returned directly by the LLM in the critique/fix loop."""

    model_config = ConfigDict(extra="forbid")

    days: list[DayPlan]
    reservations: list[ReservationAssignment]
