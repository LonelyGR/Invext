from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.db.base import Base

if TYPE_CHECKING:
    from src.models.deal_investment import DealInvestment
    from src.models.deal_participation import DealParticipation
    from src.models.referral_reward import ReferralReward

# Статусы сделки (новый поток)
DEAL_STATUS_DRAFT = "draft"
DEAL_STATUS_ACTIVE = "active"
DEAL_STATUS_CLOSED = "closed"
DEAL_STATUS_COMPLETED = "completed"


class Deal(Base):
    """Сделка с окном сбора (start_at — end_at). Участие через deal_participations."""

    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    number: Mapped[int] = mapped_column(unique=True, index=True)  # для отображения «Сделка #N»

    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DEAL_STATUS_DRAFT, index=True)

    profit_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    min_participation_usdt: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    max_participation_usdt: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    max_participants: Mapped[Optional[int]] = mapped_column(nullable=True)
    risk_level: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    risk_note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    referral_processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    close_notification_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Одноразовое напоминание о реф. бонусе за ~1 ч до end_at (не дублировать при каждом тике планировщика).
    referral_preclose_reminder_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Legacy (для обратной совместимости с данными до рефакторинга)
    percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    participations: Mapped[List["DealParticipation"]] = relationship(
        "DealParticipation",
        back_populates="deal",
        cascade="all, delete-orphan",
    )
    referral_rewards: Mapped[List["ReferralReward"]] = relationship(
        "ReferralReward",
        back_populates="deal",
        cascade="all, delete-orphan",
    )
    investments: Mapped[List["DealInvestment"]] = relationship(
        "DealInvestment",
        back_populates="deal",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Deal id={self.id} number={self.number} status={self.status}>"

