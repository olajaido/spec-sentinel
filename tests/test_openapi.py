from pathlib import Path

from spec_sentinel.config import load_config
from spec_sentinel.discovery import discover_docs
from spec_sentinel.extractor import extract_claims
from spec_sentinel.models import Verdict
from spec_sentinel.openapi import OpenApiDocument, OpenApiVerifier

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "examples" / "drifted-shop"


def _results():
    config = load_config(DEMO)
    claims = extract_claims(DEMO, discover_docs(DEMO, config)).claims
    verifier = OpenApiVerifier(OpenApiDocument.load(DEMO, DEMO / "openapi.yaml"))
    return claims, [result for claim in claims if (result := verifier.verify(claim)) is not None]


def test_demo_has_eighteen_claims() -> None:
    claims, _ = _results()
    assert len(claims) == 18


def test_mechanical_path_catches_two_seeded_divergences() -> None:
    claims, results = _results()
    by_id = {claim.id: claim for claim in claims}
    diverged = [result for result in results if result.verdict is Verdict.DIVERGED]
    assert {by_id[result.claim_id].text for result in diverged} == {
        "`GET /v1/products` accepts the optional `currency` parameter.",
        "`POST /v1/orders` returns HTTP 201 when an order is created.",
    }


def test_mechanical_results_are_stable() -> None:
    _, first = _results()
    _, second = _results()
    assert [result.model_dump_json() for result in first] == [
        result.model_dump_json() for result in second
    ]
