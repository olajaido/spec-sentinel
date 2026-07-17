"""Deterministic bootstrap extractor used before agentic enrichment."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from spec_sentinel.models import Claim, ClaimType, NormalizedAssertion, SourceLocation

ENDPOINT_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(`?/[A-Za-z0-9_{}./-]+`?)", re.I)
PARAMETER_RE = re.compile(
    r"\b(?:accepts?|requires?)\s+(?:the\s+)?(?:optional\s+|required\s+)?"
    r"`?([A-Za-z_][\w.-]*)`?\s+parameter\b",
    re.I,
)
PARAMETER_NOUN_RE = re.compile(r"`?([A-Za-z_][\w.-]*)`?\s+parameter\b", re.I)
NUMBER_RE = re.compile(r"\b(\d+(?:\.\d+)?)\b")
TESTABLE_TERMS = re.compile(
    r"\b(?:returns?|responds?|retr(?:y|ies|ied)|within|timeout|defaults?|maximum|limit|requires?|"
    r"accepts?|configured?|environment variable|fires?|sends?|writes?|reads?|stores?|"
    r"broadcasts?|publishes?|polls?|triggers?|injects?|executes?|wraps?|wrapped|hashes?|hashed|"
    r"invalidates?|guarantees?|protects?|connects?|creates?|updates?|inserts?|checks?|commits?)\b",
    re.I,
)
TECHNICAL_TERMS = re.compile(
    r"\b(?:HTTP|API|route|database|transaction|schema|table|authentication|OIDC|SSE|Redis|SQL|"
    r"SHA-?256|hash(?:ed|ing)?|state machine|environment variable|deployment|Next\.js|Node\.js|"
    r"TypeScript|Drizzle|Auth\.js|Tailwind|Vercel|Resend|AWS|Aurora|DynamoDB|webhook|"
    r"execution|condition|middleware|migration|idempotenc\w*|ACID|OCC)\b",
    re.I,
)
SQL_OPERATION_RE = re.compile(r"^(?:`?(?:SELECT|INSERT|UPDATE|DELETE)\b|commit\b)", re.I)
COUNTED_ARTIFACT_RE = re.compile(
    r"\b\d+\s+(?:tables?|routes?|endpoints?|components?|retries|attempts?|seconds?|minutes?)\b",
    re.I,
)
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")
HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
LABEL_RE = re.compile(r"^\s*\*\*(.+?):\*\*\s*$")
SKIPPED_SECTION_RE = re.compile(r"\b(?:roadmap|future work|planned features?|todo)\b", re.I)
ILLUSTRATIVE_LABEL_RE = re.compile(r"\breal-world problems?\b", re.I)
COMPARISON_ITEM_RE = re.compile(r"^\s*[-*+]\s+\*\*vs\b", re.I)


@dataclass(frozen=True)
class ExtractionOutput:
    claims: list[Claim]
    skipped_statements: int


def _clean_markdown(line: str) -> str:
    text = re.sub(r"^\s*>\s?", "", line.strip())
    text = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", text)
    text = text.replace("**", "")
    return text.strip()


def _table_cells(line: str) -> list[str]:
    return [
        _clean_markdown(cell)
        for cell in line.strip().strip("|").split("|")
        if cell.strip()
    ]


def _clean_table_row(line: str, headers: list[str] | None) -> str:
    cells = _table_cells(line)
    if headers and len(headers) == len(cells):
        cells = [
            cell
            for header, cell in zip(headers, cells, strict=True)
            if header.lower() not in {"reason", "rationale", "why"}
        ]
    return " — ".join(cells)


def _parameter_name(text: str) -> str | None:
    match = PARAMETER_RE.search(text) or PARAMETER_NOUN_RE.search(text)
    return match.group(1) if match else None


def _classify(text: str, section: str) -> ClaimType:
    lowered = text.lower()
    if _parameter_name(text):
        return ClaimType.PARAMETER
    if any(token in lowered for token in ("error", "404", "422", "500")):
        return ClaimType.ERROR
    if any(token in lowered for token in ("maximum", "limit", "within")):
        return ClaimType.LIMIT
    if any(token in lowered for token in ("environment variable", "configured", "api key")):
        return ClaimType.CONFIG
    if section.lower() in {"tech stack", "prerequisites"}:
        return ClaimType.CONFIG
    if any(token in lowered for token in ("example", "for example", "e.g.")):
        return ClaimType.EXAMPLE
    if ENDPOINT_RE.search(text):
        return ClaimType.ENDPOINT
    return ClaimType.BEHAVIOUR


def _normalize(text: str, claim_type: ClaimType) -> NormalizedAssertion:
    endpoint = ENDPOINT_RE.search(text)
    parameter = _parameter_name(text) if claim_type is ClaimType.PARAMETER else None
    number = NUMBER_RE.search(text)
    qualifiers: dict[str, str | int | float | bool] = {}
    if endpoint:
        method, raw_path = endpoint.groups()
        path = raw_path.strip("`")
        qualifiers["method"] = method.upper()
        qualifiers["path"] = path
        subject = f"{method.upper()} {path}"
    else:
        subject = parameter or re.sub(r"`([^`]+)`", r"\1", text)
        subject = re.sub(r"\s+", " ", subject).rstrip(".: ")
    if parameter:
        qualifiers["parameter"] = parameter
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


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _is_testable(text: str, raw_line: str, *, table_row: bool) -> bool:
    if ENDPOINT_RE.search(text) or TESTABLE_TERMS.search(text):
        return True
    if "state machine" in text.lower() or ("→" in text and "`" in text):
        return True
    if SQL_OPERATION_RE.search(text) or COUNTED_ARTIFACT_RE.search(text):
        return True
    if table_row:
        return bool(TECHNICAL_TERMS.search(text) or "`" in raw_line)
    if LIST_ITEM_RE.match(raw_line):
        return bool(
            TECHNICAL_TERMS.search(text)
            and ("`" in raw_line or NUMBER_RE.search(text) or "→" in text)
        )
    return bool(TECHNICAL_TERMS.search(text) and "`" in raw_line)


def _add_context_to_short_step(text: str, raw_line: str, section: str) -> str:
    if re.match(r"^\s*\d+[.)]\s+", raw_line) and len(text.split()) < 3 and section:
        return f"{section} — {text}"
    return text


def extract_claims(root: Path, files: list[Path]) -> ExtractionOutput:
    root = root.resolve()
    by_id: dict[str, Claim] = {}
    skipped = 0
    for file in files:
        lines = file.read_text(encoding="utf-8").splitlines()
        in_fence = False
        current_section = ""
        current_label = ""
        table_headers: list[str] | None = None
        for index, raw_line in enumerate(lines):
            line_number = index + 1
            stripped = raw_line.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if not stripped:
                current_label = ""
                continue
            heading = HEADING_RE.match(raw_line)
            if heading:
                current_section = _clean_markdown(heading.group(1))
                current_label = ""
                continue
            label = LABEL_RE.match(raw_line)
            if label:
                current_label = _clean_markdown(label.group(1))
                continue
            if stripped.startswith("<!--"):
                continue
            if re.match(r'^\s*>\s*"', raw_line):
                continue
            if SKIPPED_SECTION_RE.search(current_section):
                continue
            if ILLUSTRATIVE_LABEL_RE.search(current_label) or COMPARISON_ITEM_RE.match(raw_line):
                continue

            table_row = _is_table_row(raw_line)
            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            if not table_row:
                table_headers = None
            if table_row and TABLE_SEPARATOR_RE.match(next_line):
                table_headers = _table_cells(raw_line)
                continue
            if table_row and TABLE_SEPARATOR_RE.match(raw_line):
                continue
            text = (
                _clean_table_row(raw_line, table_headers)
                if table_row
                else _clean_markdown(raw_line)
            )
            text = _add_context_to_short_step(text, raw_line, current_section)
            is_testable = _is_testable(text, raw_line, table_row=table_row)
            if not is_testable:
                if text.endswith((".", "!", "?")):
                    skipped += 1
                continue
            claim_type = _classify(text, current_section)
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
