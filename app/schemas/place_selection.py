from pydantic import BaseModel, ConfigDict


class PlaceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_id: str
    selection_reason: str


class PlaceSelectionOutput(BaseModel):
    """Shape returned directly by the LLM — a flat list of selections."""

    model_config = ConfigDict(extra="forbid")

    selections: list[PlaceSelection]
