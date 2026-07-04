from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from solvra.config import Settings, load_settings
from solvra.db import create_session_factory, initialize_database
from solvra.ingest.schemas import IngestionValidationError, PaymentDataBatch
from solvra.models import Customer, MerchantAccount, Payment, Refund

ModelT = TypeVar("ModelT", Customer, MerchantAccount, Payment, Refund)


@dataclass(frozen=True)
class IngestionSummary:
    customers_inserted: int = 0
    customers_skipped: int = 0
    merchant_accounts_inserted: int = 0
    merchant_accounts_skipped: int = 0
    payments_inserted: int = 0
    payments_skipped: int = 0
    refunds_inserted: int = 0
    refunds_skipped: int = 0

    def rows(self) -> list[tuple[str, int, int]]:
        return [
            ("customers", self.customers_inserted, self.customers_skipped),
            (
                "merchant_accounts",
                self.merchant_accounts_inserted,
                self.merchant_accounts_skipped,
            ),
            ("payments", self.payments_inserted, self.payments_skipped),
            ("refunds", self.refunds_inserted, self.refunds_skipped),
        ]


def load_payment_data(path: Path) -> PaymentDataBatch:
    try:
        raw_data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise IngestionValidationError(f"could not read {path}") from exc
    except json.JSONDecodeError as exc:
        raise IngestionValidationError(f"{path} is not valid JSON") from exc

    if not isinstance(raw_data, dict):
        raise IngestionValidationError("payment data must be a JSON object")
    return PaymentDataBatch.from_mapping(raw_data)


def ingest_payments_file(
    path: Path,
    settings: Settings | None = None,
) -> IngestionSummary:
    batch = load_payment_data(path)
    active_settings = settings or load_settings()
    engine = initialize_database(active_settings)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        summary = ingest_payment_data(session, batch)
        session.commit()
        return summary


def ingest_payment_data(
    session: Session,
    batch: PaymentDataBatch,
) -> IngestionSummary:
    customers_by_external_id = get_existing_by_external_id(
        session,
        Customer,
        [item.external_id for item in batch.customers],
    )
    customer_inserted = 0
    for item in batch.customers:
        if item.external_id in customers_by_external_id:
            continue
        customer = Customer(
            external_id=item.external_id,
            email=item.email,
            name=item.name,
        )
        session.add(customer)
        customers_by_external_id[item.external_id] = customer
        customer_inserted += 1

    accounts_by_external_id = get_existing_by_external_id(
        session,
        MerchantAccount,
        [item.external_id for item in batch.merchant_accounts],
    )
    account_inserted = 0
    for item in batch.merchant_accounts:
        if item.external_id in accounts_by_external_id:
            continue
        account = MerchantAccount(
            external_id=item.external_id,
            name=item.name,
            currency=item.currency,
        )
        session.add(account)
        accounts_by_external_id[item.external_id] = account
        account_inserted += 1

    session.flush()

    payments_by_external_id = get_existing_by_external_id(
        session,
        Payment,
        [item.external_id for item in batch.payments],
    )
    payment_inserted = 0
    for item in batch.payments:
        if item.external_id in payments_by_external_id:
            continue
        payment = Payment(
            external_id=item.external_id,
            customer=customers_by_external_id[item.customer_external_id],
            merchant_account=accounts_by_external_id[item.merchant_account_external_id],
            amount=item.amount,
            currency=item.currency,
            status=item.status,
            description=item.description,
        )
        session.add(payment)
        payments_by_external_id[item.external_id] = payment
        payment_inserted += 1

    session.flush()

    refunds_by_external_id = get_existing_by_external_id(
        session,
        Refund,
        [item.external_id for item in batch.refunds],
    )
    refund_inserted = 0
    for item in batch.refunds:
        if item.external_id in refunds_by_external_id:
            continue
        refund = Refund(
            external_id=item.external_id,
            payment=payments_by_external_id[item.payment_external_id],
            amount=item.amount,
            currency=item.currency,
            reason=item.reason,
            status=item.status,
        )
        session.add(refund)
        refunds_by_external_id[item.external_id] = refund
        refund_inserted += 1

    return IngestionSummary(
        customers_inserted=customer_inserted,
        customers_skipped=len(batch.customers) - customer_inserted,
        merchant_accounts_inserted=account_inserted,
        merchant_accounts_skipped=len(batch.merchant_accounts) - account_inserted,
        payments_inserted=payment_inserted,
        payments_skipped=len(batch.payments) - payment_inserted,
        refunds_inserted=refund_inserted,
        refunds_skipped=len(batch.refunds) - refund_inserted,
    )


def get_existing_by_external_id(
    session: Session,
    model: type[ModelT],
    external_ids: list[str],
) -> dict[str, ModelT]:
    if not external_ids:
        return {}

    rows = session.scalars(
        select(model).where(model.external_id.in_(external_ids)),
    )
    return {row.external_id: row for row in rows}
