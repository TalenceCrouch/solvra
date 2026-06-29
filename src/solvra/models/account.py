from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from solvra.models.base import Base, utc_now

if TYPE_CHECKING:
    from solvra.models.ledger import LedgerEntry
    from solvra.models.payment import Payment


class MerchantAccount(Base):
    __tablename__ = "merchant_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3), default="usd")
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
        back_populates="merchant_account",
    )
    payments: Mapped[list[Payment]] = relationship(
        "Payment",
        back_populates="merchant_account",
    )
