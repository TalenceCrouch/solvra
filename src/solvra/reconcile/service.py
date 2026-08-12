from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select

from solvra.config import Settings, load_settings
from solvra.db import create_session_factory, initialize_database
from solvra.models import Payment, ReconciliationRun, Refund, WebhookEvent
from solvra.models.base import utc_now

ZERO = Decimal("0.00")


class ReconciliationRunNotFoundError(ValueError):
    pass


@dataclass(frozen=True)
class ReconciliationRunSummary:
    external_id: str
    status: str
    payment_count: int
    refund_count: int
    webhook_event_count: int
    total_payment_amount: Decimal
    total_refund_amount: Decimal
    net_amount: Decimal
    currency: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    summary_json: dict


@dataclass(frozen=True)
class ReconciliationRunRow:
    external_id: str
    status: str
    payment_count: int
    refund_count: int
    webhook_event_count: int
    net_amount: Decimal
    currency: str | None
    created_at: datetime
    completed_at: datetime | None


def create_reconciliation_run(
    settings: Settings | None = None,
) -> ReconciliationRunSummary:
    session_factory = create_reconciliation_session_factory(settings)
    with session_factory() as session:
        started_at = utc_now()
        payments = session.scalars(select(Payment)).all()
        refunds = session.scalars(select(Refund)).all()
        webhook_event_count = session.scalar(select(func.count(WebhookEvent.id))) or 0

        total_payment_amount = sum_money(payment.amount for payment in payments)
        total_refund_amount = sum_money(refund.amount for refund in refunds)
        net_amount = total_payment_amount - total_refund_amount
        currency = summarize_currency(
            [payment.currency for payment in payments],
            [refund.currency for refund in refunds],
        )
        completed_at = utc_now()

        run = ReconciliationRun(
            external_id=make_reconciliation_external_id(),
            status="completed",
            payment_count=len(payments),
            refund_count=len(refunds),
            webhook_event_count=webhook_event_count,
            total_payment_amount=total_payment_amount,
            total_refund_amount=total_refund_amount,
            net_amount=net_amount,
            currency=currency,
            started_at=started_at,
            completed_at=completed_at,
            summary_json={
                "payment_count": len(payments),
                "refund_count": len(refunds),
                "webhook_event_count": webhook_event_count,
                "total_payment_amount": str(total_payment_amount),
                "total_refund_amount": str(total_refund_amount),
                "net_amount": str(net_amount),
                "currency": currency,
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run_summary(run)


def list_reconciliation_runs(
    settings: Settings | None = None,
) -> list[ReconciliationRunRow]:
    session_factory = create_reconciliation_session_factory(settings)
    with session_factory() as session:
        runs = session.scalars(
            select(ReconciliationRun).order_by(
                ReconciliationRun.created_at.desc(),
                ReconciliationRun.external_id.desc(),
            ),
        ).all()
        return [run_row(run) for run in runs]


def get_reconciliation_run(
    external_id: str,
    settings: Settings | None = None,
) -> ReconciliationRunSummary:
    session_factory = create_reconciliation_session_factory(settings)
    with session_factory() as session:
        run = session.scalar(
            select(ReconciliationRun).where(
                ReconciliationRun.external_id == external_id,
            ),
        )
        if run is None:
            raise ReconciliationRunNotFoundError(
                f"Reconciliation run not found: {external_id}",
            )
        return run_summary(run)


def create_reconciliation_session_factory(settings: Settings | None = None):
    engine = initialize_database(settings or load_settings())
    return create_session_factory(engine)


def make_reconciliation_external_id() -> str:
    return f"rec_{uuid4().hex[:12]}"


def summarize_currency(
    payment_currencies: list[str], refund_currencies: list[str]
) -> str | None:
    currencies = {
        currency.lower()
        for currency in [*payment_currencies, *refund_currencies]
        if currency
    }
    if not currencies:
        return None
    if len(currencies) == 1:
        return next(iter(currencies))
    return "mixed"


def sum_money(amounts) -> Decimal:
    total = ZERO
    for amount in amounts:
        total += amount
    return total.quantize(ZERO)


def run_summary(run: ReconciliationRun) -> ReconciliationRunSummary:
    return ReconciliationRunSummary(
        external_id=run.external_id,
        status=run.status,
        payment_count=run.payment_count,
        refund_count=run.refund_count,
        webhook_event_count=run.webhook_event_count,
        total_payment_amount=run.total_payment_amount,
        total_refund_amount=run.total_refund_amount,
        net_amount=run.net_amount,
        currency=run.currency,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        summary_json=run.summary_json,
    )


def run_row(run: ReconciliationRun) -> ReconciliationRunRow:
    return ReconciliationRunRow(
        external_id=run.external_id,
        status=run.status,
        payment_count=run.payment_count,
        refund_count=run.refund_count,
        webhook_event_count=run.webhook_event_count,
        net_amount=run.net_amount,
        currency=run.currency,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )
