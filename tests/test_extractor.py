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


def test_extracts_structured_technical_claims_and_skips_future_work(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Service\n\n"
        "## Architecture\n\n"
        "| Concern | Choice | Reason |\n"
        "|---|---|---|\n"
        "| Framework | Next.js 16 App Router | Server Components and API routes |\n\n"
        "## Execution\n\n"
        "1. Check pact is `ACTIVE` before execution.\n"
        "2. `INSERT INTO audit_log` with a SHA-256 hash entry.\n\n"
        "**State machine:** `DRAFT → ACTIVE → EXECUTED`\n\n"
        "## Roadmap\n\n"
        "- Webhook triggers will be added after launch.\n",
        encoding="utf-8",
    )

    output = extract_claims(tmp_path, [readme])

    assert [claim.source_locations[0].line for claim in output.claims] == [7, 11, 12, 14]
    assert output.claims[0].text == "Framework — Next.js 16 App Router"
    assert output.claims[-1].text == "State machine: `DRAFT → ACTIVE → EXECUTED`"
    assert all("after launch" not in claim.text for claim in output.claims)


def test_requires_without_explicit_parameter_word_is_not_a_parameter_claim(
    tmp_path: Path,
) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "Pact requires SQL to enforce relational integrity.\n"
        "`POST /v1/pacts` requires the `owner_id` parameter.\n",
        encoding="utf-8",
    )

    output = extract_claims(tmp_path, [readme])

    assert [claim.type for claim in output.claims] == [
        ClaimType.BEHAVIOUR,
        ClaimType.PARAMETER,
    ]
    assert "parameter" not in output.claims[0].normalized_assertion.qualifiers
    assert output.claims[1].normalized_assertion.qualifiers["parameter"] == "owner_id"


def test_skips_illustrative_marketing_and_architecture_comparisons(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "**Real-world problems Pact solves:**\n"
        "- Freelancer submits work → Client accepts → Project closes with an audit trail\n\n"
        "## Architecture decision\n\n"
        "- **vs DynamoDB** — relational integrity requires SQL\n"
        "- Every event is hashed with the previous SHA-256 entry.\n",
        encoding="utf-8",
    )

    output = extract_claims(tmp_path, [readme])

    assert [claim.text for claim in output.claims] == [
        "Every event is hashed with the previous SHA-256 entry."
    ]
    assert output.claims[0].type is ClaimType.BEHAVIOUR
