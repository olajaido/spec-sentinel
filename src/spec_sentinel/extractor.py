"""Deterministic bootstrap extractor used before agentic enrichment."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from spec_sentinel.models import Claim, ClaimType, NormalizedAssertion, SourceLocation

ENDPOINT_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(`?/[A-Za-z0-9_{}./-]+`?)", re.I)
PARAMETER_RE = re.compile(
    r"\b(?:accepts?|requires?)\s+(?:the\s+)?(?:optional\s+|required\s+)?"
    r"`?([A-Za-z_][\w.-]*)`?(?:\s+parameter)?",
    re.I,
)
NUMBER_RE = re.compile(r"\b(\d+(?:\.\d+)?)\b")
TESTABLE_TERMS = re.compile(
    r"\b(?:returns?|responds?|retr(?:y|ies|ied)|within|timeout|defaults?|maximum|limit|requires?|"
    r"accepts?|configured?|environment variable|fires?|sends?)\b",
    re.I,
)


@dataclass(frozen=True)
class ExtractionOutput:
    claims: list[Claim]
    skipped_statements: int


def _clean_markdown(line: str) -> str:
    text = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", line.strip())
    return text.strip()


def _classify(text: str) -> ClaimType:
    lowered = text.lower()
    if PARAMETER_RE.search(text) or "parameter" in lowered:
        return ClaimType.PARAMETER
    if any(token in lowered for token in ("error", "404", "422", "500")):
        return ClaimType.ERROR
    if any(token in lowered for token in ("maximum", "limit", "within")):
        return ClaimType.LIMIT
    if any(token in lowered for token in ("environment variable", "configured", "api key")):
        return ClaimType.CONFIG
    if any(token in lowered for token in ("example", "for example", "e.g.")):
        return ClaimType.EXAMPLE
    if ENDPOINT_RE.search(text):
        return ClaimType.ENDPOINT
    return ClaimType.BEHAVIOUR


def _normalize(text: str, claim_type: ClaimType) -> NormalizedAssertion:
    endpoint = ENDPOINT_RE.search(text)
    parameter = PARAMETER_RE.search(text)
    number = NUMBER_RE.search(text)
    qualifiers: dict[str, str | int | float | bool] = {}
    if endpoint:
        method, raw_path = endpoint.groups()
        path = raw_path.strip("`")
        qualifiers["method"] = method.upper()
        qualifiers["path"] = path
        subject = f"{method.upper()} {path}"
    else:
        subject = parameter.group(1) if parameter else text.split(" ", 1)[0].strip("`:. ")
    if parameter:
        qualifiers["parameter"] = parameter.group(1)
    value: str | int | float | bool | None = None
    if number:
        raw = number.group(1)
        value = float(raw) if "." in raw else int(raw)
    return NormalizedAssertion(
        subject=subject or claim_type.value,
        predicate=claim_type.value,
        object=value,
        qualifiers=qualifiers,
    )


def extract_claims(root: Path, files: list[Path]) -> ExtractionOutput:
    root = root.resolve()
    by_id: dict[str, Claim] = {}
    skipped = 0
    in_fence = False
    for file in files:
        for line_number, raw_line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            stripped = raw_line.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or not stripped or stripped.startswith(("#", "<!--")):
                continue
            text = _clean_markdown(raw_line)
            is_testable = bool(ENDPOINT_RE.search(text) or TESTABLE_TERMS.search(text))
            if not is_testable:
                if text.endswith((".", "!", "?")):
                    skipped += 1
                continue
            claim_type = _classify(text)
            assertion = _normalize(text, claim_type)
            claim_id = Claim.stable_id(assertion)
            location = SourceLocation(
                file=file.resolve().relative_to(root).as_posix(),
                line=line_number,
            )
            if claim_id in by_id:
                existing = by_id[claim_id]
                existing.source_locations.append(location)
            else:
                by_id[claim_id] = Claim(
                    id=claim_id,
                    type=claim_type,
                    text=text,
                    normalized_assertion=assertion,
                    source_locations=[location],
                    confidence=0.75,
                )
    return ExtractionOutput(claims=list(by_id.values()), skipped_statements=skipped)
