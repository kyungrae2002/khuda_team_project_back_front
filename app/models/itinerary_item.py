import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ReservationNeeded(str, enum.Enum):
    required = "required"
    recommended = "recommended"
    unnecessary = "unnecessary"


class ItineraryItem(Base):
    __tablename__ = "itinerary_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("travel_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    place_id: Mapped[int] = mapped_column(ForeignKey("places.id"), nullable=False, index=True)
    day_index: Mapped[int] = mapped_column(Integer, nullable=False)
    order_in_day: Mapped[int] = mapped_column(Integer, nullable=False)
    arrival_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    reservation_needed: Mapped[ReservationNeeded] = mapped_column(
        Enum(ReservationNeeded, name="reservation_needed"),
        nullable=False,
        default=ReservationNeeded.unnecessary,
    )

    session: Mapped["TravelSession"] = relationship(back_populates="itinerary_items")
    place: Mapped["Place"] = relationship(back_populates="itinerary_items")
