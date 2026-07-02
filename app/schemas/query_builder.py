import enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.slot import SlotField


class PlaceCategory(str, enum.Enum):
    restaurant = "restaurant"
    cafe = "cafe"
    bakery = "bakery"
    bar = "bar"
    night_club = "night_club"
    tourist_attraction = "tourist_attraction"
    museum = "museum"
    art_gallery = "art_gallery"
    park = "park"
    amusement_park = "amusement_park"
    zoo = "zoo"
    aquarium = "aquarium"
    shopping_mall = "shopping_mall"
    lodging = "lodging"
    spa = "spa"
    movie_theater = "movie_theater"


class PlaceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_text: str
    search_type: Literal["text", "nearby"]
    category: PlaceCategory


class PlaceQueriesOutput(BaseModel):
    """Shape returned directly by the LLM — queries only. Whether the search
    can run at all (missing_critical_slots) is decided in Python before the
    model is ever called, not by the model."""

    model_config = ConfigDict(extra="forbid")

    queries: list[PlaceQuery]


class QueryBuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queries: list[PlaceQuery] = Field(default_factory=list)
    missing_critical_slots: list[SlotField] = Field(default_factory=list)
