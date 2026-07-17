from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.settings import WEBHOOK_DEADLINE_SECONDS


@dataclass(frozen=True)
class WebhookDelivery:
    purchase_id: str
    created_at: datetime
    delivered_at: datetime
    deadline: datetime


WEBHOOK_DELIVERIES: list[WebhookDelivery] = []


def delivery_deadline(created_at: datetime) -> datetime:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at + timedelta(seconds=WEBHOOK_DEADLINE_SECONDS)


def fire_purchase_webhook(purchase_id: str, created_at: datetime | None = None) -> WebhookDelivery:
    created_at = created_at or datetime.now(UTC)
    delivered_at = datetime.now(UTC)
    deadline = delivery_deadline(created_at)
    if delivered_at > deadline:
        raise TimeoutError("purchase webhook missed its delivery deadline")
    delivery = WebhookDelivery(
        purchase_id=purchase_id,
        created_at=created_at,
        delivered_at=delivered_at,
        deadline=deadline,
    )
    WEBHOOK_DELIVERIES.append(delivery)
    return delivery
