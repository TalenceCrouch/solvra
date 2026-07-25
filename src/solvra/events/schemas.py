from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUPPORTED_EVENT_TYPES = {
    "payment.created",
    "payment.succeeded",
    "payment.failed",
    "refund.created",
    "refund.succeeded",
    "refund.failed",
}


class EventValidationError(ValueError):
    pass


@dataclass(frozen=True)
class WebhookEventInput:
    external_id: str
    event_type: str
    source: str | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class EventDataBatch:
    events: list[WebhookEventInput]

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> EventDataBatch:
        events = [
            parse_event(item, index)
            for index, item in enumerate(require_events_list(data))
        ]
        if not events:
            raise EventValidationError("events must not be empty")

        validate_unique_external_ids(events)
        return cls(events=events)


def require_events_list(data: dict[str, Any]) -> list[Any]:
    value = data.get("events")
    if not isinstance(value, list):
        raise EventValidationError("events must be a list")
    return value


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EventValidationError(f"{label} must be an object")
    return value


def require_string(item: dict[str, Any], field: str, label: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EventValidationError(f"{label}.{field} is required")
    return value.strip()


def optional_string(item: dict[str, Any], field: str) -> str | None:
    value = item.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise EventValidationError(f"{field} must be a string")
    return value.strip() or None


def parse_event(value: Any, index: int) -> WebhookEventInput:
    label = f"events[{index}]"
    item = require_mapping(value, label)
    event_type = require_string(item, "event_type", label)
    if event_type not in SUPPORTED_EVENT_TYPES:
        raise EventValidationError(f"{label}.event_type is unsupported")

    payload = item.get("payload")
    if not isinstance(payload, dict) or not payload:
        raise EventValidationError(f"{label}.payload must be a non-empty object")

    return WebhookEventInput(
        external_id=require_string(item, "external_id", label),
        event_type=event_type,
        source=optional_string(item, "source"),
        payload=payload,
    )


def validate_unique_external_ids(events: list[WebhookEventInput]) -> None:
    seen: set[str] = set()
    for event in events:
        if event.external_id in seen:
            raise EventValidationError("duplicate event external_id")
        seen.add(event.external_id)
