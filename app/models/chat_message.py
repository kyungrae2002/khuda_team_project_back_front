from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("travel_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender: Mapped[str] = mapped_column(String(100), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # True for 사진/이모티콘 attachment placeholders parsed from Kakao exports —
    # downstream slot-extraction should filter these out of conversational context.
    is_media: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    session: Mapped["TravelSession"] = relationship(back_populates="chat_messages")
