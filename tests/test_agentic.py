import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from openai import RateLimitError

from spec_sentinel.agentic import AgentConclusion, AgenticVerifier, RepositoryTools
from spec_sentinel.config import SentinelConfig
from spec_sentinel.models import (
    Claim,
    ClaimType,
    NormalizedAssertion,
    SourceLocation,
    Verdict,
)


class FakeResponses:
    def __init__(self, responses):
        self._responses = iter(responses)

    def parse(self, **kwargs):
        del kwargs
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def _claim() -> Claim:
    assertion = NormalizedAssertion(subject="requests", predicate="behaviour", object=3)
    return Claim(
        id=Claim.stable_id(assertion),
        type=ClaimType.BEHAVIOUR,
        text="Failed requests are retried 3 times.",
        normalized_assertion=assertion,
        source_locations=[SourceLocation(file="README.md", line=1)],
        confidence=0.9,
    )


def _rate_limit_error() -> RateLimitError:
    response = httpx.Response(
        429,
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
    )
    return RateLimitError(
        "provider message must remain private",
        response=response,
        body={"error": {"code": "rate_limit_exceeded"}},
    )


def test_repository_tools_reject_out_of_scope_reads(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("RETRIES = 2\n", encoding="utf-8")
    tools = RepositoryTools(tmp_path, [source], max_file_bytes=1000)
    assert "RETRIES" in tools.search("retries")
    assert "outside the allowed" in tools.read_file("../secret.txt")


def test_low_confidence_divergence_degrades_to_ambiguous(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("RETRIES = 2\n", encoding="utf-8")
    conclusion = AgentConclusion.model_validate(
        {
            "verdict": "diverged",
            "confidence": 0.7,
            "rationale": "The values differ.",
            "evidence": [{"kind": "code", "file": "app.py", "line": 1, "supports": False}],
            "direction": "undetermined",
        }
    )
    response = SimpleNamespace(output=[], output_parsed=conclusion)
    client = SimpleNamespace(responses=FakeResponses([response]))
    verifier = AgenticVerifier(
        RepositoryTools(tmp_path, [source], 1000), SentinelConfig(), client=client
    )
    assert verifier.verify(_claim()).verdict is Verdict.AMBIGUOUS


def test_tool_budget_exhaustion_returns_ambiguous_with_trail(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("RETRIES = 2\n", encoding="utf-8")
    call = SimpleNamespace(
        type="function_call",
        name="search",
        arguments=json.dumps({"query": "RETRIES", "max_results": 10}),
        call_id="call_1",
    )
    response = SimpleNamespace(output=[call], output_parsed=None)
    client = SimpleNamespace(responses=FakeResponses([response]))
    config = SentinelConfig(max_steps_per_claim=1)
    verifier = AgenticVerifier(RepositoryTools(tmp_path, [source], 1000), config, client=client)
    result = verifier.verify(_claim())
    assert result.verdict is Verdict.AMBIGUOUS
    assert len(result.search_trail) == 1
    assert "budget" in result.rationale


def test_rate_limit_is_retried_with_bounded_backoff(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("RETRIES = 3\n", encoding="utf-8")
    conclusion = AgentConclusion.model_validate(
        {
            "verdict": "verified",
            "confidence": 0.95,
            "rationale": "The documented retry count matches the implementation.",
            "evidence": [{"kind": "code", "file": "app.py", "line": 1, "supports": True}],
        }
    )
    response = SimpleNamespace(output=[], output_parsed=conclusion)
    client = SimpleNamespace(responses=FakeResponses([_rate_limit_error(), response]))
    delays: list[float] = []
    verifier = AgenticVerifier(
        RepositoryTools(tmp_path, [source], 1000),
        SentinelConfig(),
        client=client,
        sleep=delays.append,
        jitter=lambda: 0.0,
    )

    result = verifier.verify(_claim())

    assert result.verdict is Verdict.VERIFIED
    assert delays == [2.0]


def test_rate_limit_raises_after_retry_budget_is_exhausted(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("RETRIES = 3\n", encoding="utf-8")
    errors = [_rate_limit_error() for _ in range(5)]
    client = SimpleNamespace(responses=FakeResponses(errors))
    delays: list[float] = []
    verifier = AgenticVerifier(
        RepositoryTools(tmp_path, [source], 1000),
        SentinelConfig(),
        client=client,
        sleep=delays.append,
        jitter=lambda: 0.0,
    )

    try:
        verifier.verify(_claim())
    except RateLimitError:
        pass
    else:
        raise AssertionError("expected RateLimitError")

    assert delays == [2.0, 4.0, 8.0, 16.0]
