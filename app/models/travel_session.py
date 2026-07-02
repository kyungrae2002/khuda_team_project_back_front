from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class TravelSession(Base):
    __tablename__ = "travel_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    chat_messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    slots: Mapped[list["Slot"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    itinerary_items: Mapped[list["ItineraryItem"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    validation_logs: Mapped[list["ValidationLog"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
