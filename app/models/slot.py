import enum

from sqlalchemy import Enum, Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SlotField(str, enum.Enum):
    destination = "destination"
    date = "date"
    budget = "budget"
    headcount = "headcount"
    transport = "transport"
    constraint = "constraint"
    wishlist = "wishlist"


class SlotStatus(str, enum.Enum):
    confirmed = "confirmed"
    undecided = "undecided"
    conflict = "conflict"


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("travel_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field: Mapped[SlotField] = mapped_column(Enum(SlotField, name="slot_field"), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[SlotStatus] = mapped_column(
        Enum(SlotStatus, name="slot_status"), nullable=False, default=SlotStatus.undecided
    )
    # References ChatMessage.id. Kept as a plain array (not a join table) since a slot
    # is derived from a small, fixed set of source messages rather than a queried relation.
    evidence_message_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    session: Mapped["TravelSession"] = relationship(back_populates="slots")
