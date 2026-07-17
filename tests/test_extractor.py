from pathlib import Path

from spec_sentinel.config import SentinelConfig
from spec_sentinel.discovery import discover_docs
from spec_sentinel.extractor import extract_claims
from spec_sentinel.models import ClaimType


def test_extracts_endpoint_and_skips_marketing(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Example\n\nThe delightful API for everyone.\n\n- `GET /v1/items` returns 200.\n",
        encoding="utf-8",
    )
    files = discover_docs(tmp_path, SentinelConfig(docs=["README.md"]))
    output = extract_claims(tmp_path, files)
    assert len(output.claims) == 1
    assert output.claims[0].type is ClaimType.ENDPOINT
    assert output.claims[0].source_locations[0].line == 5
    assert output.skipped_statements == 1


def test_deduplicates_normalized_endpoint_claims(tmp_path: Path) -> None:
    first = tmp_path / "README.md"
    second = tmp_path / "docs.md"
    first.write_text("`GET /v1/items` returns products.\n", encoding="utf-8")
    second.write_text("GET /v1/items returns the current products.\n", encoding="utf-8")
    output = extract_claims(tmp_path, [first, second])
    assert len(output.claims) == 1
    assert len(output.claims[0].source_locations) == 2


def test_parameter_names_and_past_tense_retries_are_preserved(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "- `GET /v1/items` accepts the optional `category` parameter.\n"
        "- Failed requests are retried up to 3 times.\n",
        encoding="utf-8",
    )
    output = extract_claims(tmp_path, [readme])
    assert len(output.claims) == 2
    assert output.claims[0].normalized_assertion.qualifiers["parameter"] == "category"
    assert output.claims[1].normalized_assertion.object == 3
