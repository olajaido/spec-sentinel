"""Runtime settings. Constants are explicit to make static verification deterministic."""

import os

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_PURCHASE_QUANTITY = 10
DEFAULT_RETRY_ATTEMPTS = 2
INVENTORY_TIMEOUT_SECONDS = 10
WEBHOOK_DEADLINE_SECONDS = 60
API_KEY_ENVIRONMENT_VARIABLE = "DRIFTED_SHOP_API_KEY"


def api_key() -> str | None:
    return os.getenv(API_KEY_ENVIRONMENT_VARIABLE)
