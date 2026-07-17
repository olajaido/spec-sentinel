import pytest
from app.settings import DEFAULT_RETRY_ATTEMPTS


@pytest.mark.xfail(
    strict=True, reason="Seeded bug: implementation drifted from intended retry policy"
)
def test_inventory_retries_match_product_intent() -> None:
    assert DEFAULT_RETRY_ATTEMPTS == 3
