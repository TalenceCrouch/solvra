from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from solvra.models.base import Base, utc_now

if TYPE_CHECKING:
    from solvra.models.ledger import LedgerEntry
    from solvra.models.payment import Payment


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_refunds_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(120), unique=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    ledger_entries: Mapped[list[LedgerEntry]] = relationship(
        "LedgerEntry",
        back_populates="refund",
    )
    payment: Mapped[Payment] = relationship(
        "Payment",
        back_populates="refunds",
    )
