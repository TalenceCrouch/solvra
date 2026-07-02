from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

PAYMENT_STATUSES = {"pending", "succeeded", "failed", "canceled"}
REFUND_STATUSES = {"pending", "succeeded", "failed"}


class IngestionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CustomerInput:
    external_id: str
    email: str | None
    name: str | None


@dataclass(frozen=True)
class MerchantAccountInput:
    external_id: str
    name: str
    currency: str


@dataclass(frozen=True)
class PaymentInput:
    external_id: str
    customer_external_id: str
    merchant_account_external_id: str
    amount: Decimal
    currency: str
    status: str
    description: str | None


@dataclass(frozen=True)
class RefundInput:
    external_id: str
    payment_external_id: str
    amount: Decimal
    currency: str
    reason: str | None
    status: str


@dataclass(frozen=True)
class PaymentDataBatch:
    customers: list[CustomerInput]
    merchant_accounts: list[MerchantAccountInput]
    payments: list[PaymentInput]
    refunds: list[RefundInput]

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> PaymentDataBatch:
        customers = [
            parse_customer(item, index)
            for index, item in enumerate(require_list(data, "customers"))
        ]
        merchant_accounts = [
            parse_merchant_account(item, index)
            for index, item in enumerate(require_list(data, "merchant_accounts"))
        ]
        payments = [
            parse_payment(item, index)
            for index, item in enumerate(require_list(data, "payments"))
        ]
        refunds = [
            parse_refund(item, index)
            for index, item in enumerate(require_list(data, "refunds"))
        ]

        validate_unique("customer", [item.external_id for item in customers])
        validate_unique(
            "merchant account",
            [item.external_id for item in merchant_accounts],
        )
        validate_unique("payment", [item.external_id for item in payments])
        validate_unique("refund", [item.external_id for item in refunds])
        validate_references(customers, merchant_accounts, payments, refunds)

        return cls(
            customers=customers,
            merchant_accounts=merchant_accounts,
            payments=payments,
            refunds=refunds,
        )


def require_list(data: dict[str, Any], field: str) -> list[Any]:
    value = data.get(field)
    if not isinstance(value, list):
        raise IngestionValidationError(f"{field} must be a list")
    return value


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IngestionValidationError(f"{label} must be an object")
    return value


def require_string(item: dict[str, Any], field: str, label: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise IngestionValidationError(f"{label}.{field} is required")
    return value.strip()


def optional_string(item: dict[str, Any], field: str) -> str | None:
    value = item.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise IngestionValidationError(f"{field} must be a string")
    return value.strip() or None


def parse_amount(item: dict[str, Any], label: str) -> Decimal:
    value = item.get("amount")
    if not isinstance(value, str):
        raise IngestionValidationError(f"{label}.amount must be a string")

    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise IngestionValidationError(f"{label}.amount is invalid") from exc

    if amount <= Decimal("0") or amount.as_tuple().exponent < -2:
        raise IngestionValidationError(f"{label}.amount is invalid")
    return amount


def parse_customer(value: Any, index: int) -> CustomerInput:
    label = f"customers[{index}]"
    item = require_mapping(value, label)
    return CustomerInput(
        external_id=require_string(item, "external_id", label),
        email=optional_string(item, "email"),
        name=optional_string(item, "name"),
    )


def parse_merchant_account(value: Any, index: int) -> MerchantAccountInput:
    label = f"merchant_accounts[{index}]"
    item = require_mapping(value, label)
    return MerchantAccountInput(
        external_id=require_string(item, "external_id", label),
        name=require_string(item, "name", label),
        currency=require_string(item, "currency", label).lower(),
    )


def parse_payment(value: Any, index: int) -> PaymentInput:
    label = f"payments[{index}]"
    item = require_mapping(value, label)
    status = require_string(item, "status", label)
    if status not in PAYMENT_STATUSES:
        raise IngestionValidationError(f"{label}.status is invalid")

    return PaymentInput(
        external_id=require_string(item, "external_id", label),
        customer_external_id=require_string(item, "customer_external_id", label),
        merchant_account_external_id=require_string(
            item,
            "merchant_account_external_id",
            label,
        ),
        amount=parse_amount(item, label),
        currency=require_string(item, "currency", label).lower(),
        status=status,
        description=optional_string(item, "description"),
    )


def parse_refund(value: Any, index: int) -> RefundInput:
    label = f"refunds[{index}]"
    item = require_mapping(value, label)
    status = require_string(item, "status", label)
    if status not in REFUND_STATUSES:
        raise IngestionValidationError(f"{label}.status is invalid")

    return RefundInput(
        external_id=require_string(item, "external_id", label),
        payment_external_id=require_string(item, "payment_external_id", label),
        amount=parse_amount(item, label),
        currency=require_string(item, "currency", label).lower(),
        reason=optional_string(item, "reason"),
        status=status,
    )


def validate_unique(label: str, external_ids: list[str]) -> None:
    seen: set[str] = set()
    for external_id in external_ids:
        if external_id in seen:
            raise IngestionValidationError(f"duplicate {label} external_id")
        seen.add(external_id)


def validate_references(
    customers: list[CustomerInput],
    merchant_accounts: list[MerchantAccountInput],
    payments: list[PaymentInput],
    refunds: list[RefundInput],
) -> None:
    customer_ids = {item.external_id for item in customers}
    account_ids = {item.external_id for item in merchant_accounts}
    payment_ids = {item.external_id for item in payments}

    for payment in payments:
        if payment.customer_external_id not in customer_ids:
            raise IngestionValidationError(
                f"unknown customer reference: {payment.customer_external_id}",
            )
        if payment.merchant_account_external_id not in account_ids:
            raise IngestionValidationError(
                "unknown merchant account reference: "
                f"{payment.merchant_account_external_id}",
            )

    for refund in refunds:
        if refund.payment_external_id not in payment_ids:
            raise IngestionValidationError(
                f"unknown payment reference: {refund.payment_external_id}",
            )
