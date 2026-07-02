from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ValidationLog(Base):
    __tablename__ = "validation_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("travel_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    violations: Mapped[list | dict] = mapped_column(JSONB, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    session: Mapped["TravelSession"] = relationship(back_populates="validation_logs")
