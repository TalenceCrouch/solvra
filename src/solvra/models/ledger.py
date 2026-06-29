from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from solvra.models.base import Base, utc_now

if TYPE_CHECKING:
    from solvra.models.account import MerchantAccount
    from solvra.models.payment import Payment
    from solvra.models.refund import Refund


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('payment', 'refund', 'payout', 'adjustment')",
            name="ck_ledger_entries_entry_type",
        ),
        CheckConstraint(
            "direction IN ('debit', 'credit')",
            name="ck_ledger_entries_direction",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(120), unique=True)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"))
    refund_id: Mapped[int | None] = mapped_column(ForeignKey("refunds.id"))
    merchant_account_id: Mapped[int] = mapped_column(
        ForeignKey("merchant_accounts.id"),
    )
    entry_type: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    direction: Mapped[str] = mapped_column(String(10))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )

    merchant_account: Mapped[MerchantAccount] = relationship(
        "MerchantAccount",
        back_populates="ledger_entries",
    )
    payment: Mapped[Payment | None] = relationship(
        "Payment",
        back_populates="ledger_entries",
    )
    refund: Mapped[Refund | None] = relationship(
        "Refund",
        back_populates="ledger_entries",
    )
