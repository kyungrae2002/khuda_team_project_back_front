from datetime import datetime

from sqlalchemy import ARRAY, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class PlaceSearchCache(Base):
    """Records the last time a given (query_text, search_type, category) was
    searched against the Google Places API, and which places it returned —
    lets get_or_fetch_place() skip the API call within the freshness window."""

    __tablename__ = "place_search_cache"
    __table_args__ = (
        UniqueConstraint("query_text", "search_type", "category", name="uq_place_search_cache_query"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    query_text: Mapped[str] = mapped_column(String(500), nullable=False)
    search_type: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    place_ids: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    searched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
