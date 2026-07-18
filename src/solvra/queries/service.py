from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from solvra.config import Settings, load_settings
from solvra.db import create_session_factory, initialize_database
from solvra.models import Customer, MerchantAccount, Payment, Refund


@dataclass(frozen=True)
class PaymentRow:
    external_id: str
    customer: str
    merchant_account: str
    amount: Decimal
    currency: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class RefundRow:
    external_id: str
    payment_external_id: str
    amount: Decimal
    currency: str
    status: str
    reason: str | None
    created_at: datetime


@dataclass(frozen=True)
class CustomerRow:
    external_id: str
    email: str | None
    name: str | None
    created_at: datetime
    payment_count: int


@dataclass(frozen=True)
class PaymentRefundRow:
    external_id: str
    amount: Decimal
    currency: str
    status: str
    reason: str | None


@dataclass(frozen=True)
class PaymentDetail:
    external_id: str
    amount: Decimal
    currency: str
    status: str
    description: str | None
    customer_external_id: str
    customer_email: str | None
    customer_name: str | None
    merchant_account_external_id: str
    merchant_account_name: str
    refunds: list[PaymentRefundRow]
    created_at: datetime


def list_payments(settings: Settings | None = None) -> list[PaymentRow]:
    session_factory = create_query_session_factory(settings)
    with session_factory() as session:
        payments = session.scalars(
            select(Payment)
            .options(
                selectinload(Payment.customer),
                selectinload(Payment.merchant_account),
            )
            .order_by(Payment.created_at, Payment.external_id),
        ).all()

        return [
            PaymentRow(
                external_id=payment.external_id,
                customer=display_customer(payment.customer),
                merchant_account=display_merchant_account(payment.merchant_account),
                amount=payment.amount,
                currency=payment.currency,
                status=payment.status,
                created_at=payment.created_at,
            )
            for payment in payments
        ]


def payment_detail(
    external_id: str,
    settings: Settings | None = None,
) -> PaymentDetail | None:
    session_factory = create_query_session_factory(settings)
    with session_factory() as session:
        payment = session.scalar(
            select(Payment)
            .where(Payment.external_id == external_id)
            .options(
                selectinload(Payment.customer),
                selectinload(Payment.merchant_account),
                selectinload(Payment.refunds),
            ),
        )
        if payment is None:
            return None

        return PaymentDetail(
            external_id=payment.external_id,
            amount=payment.amount,
            currency=payment.currency,
            status=payment.status,
            description=payment.description,
            customer_external_id=payment.customer.external_id,
            customer_email=payment.customer.email,
            customer_name=payment.customer.name,
            merchant_account_external_id=payment.merchant_account.external_id,
            merchant_account_name=payment.merchant_account.name,
            refunds=[
                PaymentRefundRow(
                    external_id=refund.external_id,
                    amount=refund.amount,
                    currency=refund.currency,
                    status=refund.status,
                    reason=refund.reason,
                )
                for refund in sorted(payment.refunds, key=lambda item: item.external_id)
            ],
            created_at=payment.created_at,
        )


def list_customers(settings: Settings | None = None) -> list[CustomerRow]:
    session_factory = create_query_session_factory(settings)
    with session_factory() as session:
        rows = session.execute(
            select(Customer, func.count(Payment.id))
            .outerjoin(Payment)
            .group_by(Customer.id)
            .order_by(Customer.created_at, Customer.external_id),
        ).all()

        return [
            CustomerRow(
                external_id=customer.external_id,
                email=customer.email,
                name=customer.name,
                created_at=customer.created_at,
                payment_count=payment_count,
            )
            for customer, payment_count in rows
        ]


def list_refunds(settings: Settings | None = None) -> list[RefundRow]:
    session_factory = create_query_session_factory(settings)
    with session_factory() as session:
        refunds = session.scalars(
            select(Refund)
            .options(selectinload(Refund.payment))
            .order_by(Refund.created_at, Refund.external_id),
        ).all()

        return [
            RefundRow(
                external_id=refund.external_id,
                payment_external_id=refund.payment.external_id,
                amount=refund.amount,
                currency=refund.currency,
                status=refund.status,
                reason=refund.reason,
                created_at=refund.created_at,
            )
            for refund in refunds
        ]


def create_query_session_factory(settings: Settings | None = None):
    engine = initialize_database(settings or load_settings())
    return create_session_factory(engine)


def display_customer(customer: Customer) -> str:
    return customer.external_id


def display_merchant_account(account: MerchantAccount) -> str:
    return account.external_id
