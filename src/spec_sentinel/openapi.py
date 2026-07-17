"""Deterministic OpenAPI verification for schema-representable claims."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml

from spec_sentinel.models import (
    Claim,
    ClaimType,
    Direction,
    DirectionAssessment,
    Evidence,
    EvidenceKind,
    SourceLocation,
    Verdict,
    VerificationResult,
)

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


@dataclass(frozen=True)
class OpenApiDocument:
    root: Path
    path: Path
    data: dict[str, Any]
    lines: list[str]

    @classmethod
    def load(cls, root: Path, path: Path) -> OpenApiDocument:
        root = root.resolve()
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or resolved.is_symlink():
            raise ValueError("OpenAPI document must be a regular file inside the repository")
        text = resolved.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if not isinstance(data, dict) or not str(data.get("openapi", "")).startswith("3."):
            raise ValueError("only OpenAPI 3.x documents are supported")
        return cls(root=root, path=resolved, data=data, lines=text.splitlines())

    @property
    def relative_path(self) -> str:
        return self.path.relative_to(self.root).as_posix()

    def line_for_key(self, key: str, *, fallback: int = 1) -> int:
        rendered = f"{key}:"
        quoted = {f"'{key}':", f'"{key}":'}
        for index, line in enumerate(self.lines, 1):
            stripped = line.strip()
            if stripped == rendered or stripped in quoted:
                return index
        return fallback

    def snippet(self, line: int) -> str:
        if 1 <= line <= len(self.lines):
            return self.lines[line - 1].strip()
        return "OpenAPI document"

    def evidence(self, key: str, *, supports: bool, fallback: int = 1) -> Evidence:
        line = self.line_for_key(key, fallback=fallback)
        return Evidence(
            kind=EvidenceKind.SPEC,
            location=SourceLocation(file=self.relative_path, line=line),
            snippet=self.snippet(line),
            supports=supports,
        )


class OpenApiVerifier:
    def __init__(self, document: OpenApiDocument) -> None:
        self.document = document

    def verify(self, claim: Claim) -> VerificationResult | None:
        assertion = claim.normalized_assertion
        method = assertion.qualifiers.get("method")
        path = assertion.qualifiers.get("path")
        if not isinstance(method, str) or not isinstance(path, str):
            return None
        method = method.lower()
        if method not in HTTP_METHODS:
            return None
        paths = self.document.data.get("paths", {})
        if not isinstance(paths, dict):
            return None
        path_item = paths.get(path)
        if not isinstance(path_item, dict):
            alternative = self._closest_path(path, method, paths)
            evidence_key = alternative or "paths"
            rationale = f"The OpenAPI document has no {method.upper()} operation at {path}."
            if alternative:
                rationale += f" The closest operation using that method is {alternative}."
            return self._diverged(
                claim, rationale, self.document.evidence(evidence_key, supports=False)
            )
        operation = path_item.get(method)
        if not isinstance(operation, dict):
            evidence = self.document.evidence(path, supports=False)
            return self._diverged(
                claim,
                f"The path {path} exists, but it has no {method.upper()} operation.",
                evidence,
            )
        if claim.type is ClaimType.PARAMETER:
            return self._verify_parameter(claim, path, method, path_item, operation)
        status_code = self._status_code(claim)
        if status_code is not None:
            responses = operation.get("responses", {})
            if not isinstance(responses, dict) or str(status_code) not in {
                str(code) for code in responses
            }:
                evidence = self.document.evidence(path, supports=False)
                return self._diverged(
                    claim,
                    f"{method.upper()} {path} does not declare HTTP {status_code} in OpenAPI.",
                    evidence,
                )
            return self._verified(
                claim,
                f"OpenAPI declares HTTP {status_code} for {method.upper()} {path}.",
                self.document.evidence(
                    str(status_code), supports=True, fallback=self.document.line_for_key(path)
                ),
            )
        return self._verified(
            claim,
            f"OpenAPI declares {method.upper()} {path}.",
            self.document.evidence(path, supports=True),
        )

    def _verify_parameter(
        self,
        claim: Claim,
        path: str,
        method: str,
        path_item: dict[str, Any],
        operation: dict[str, Any],
    ) -> VerificationResult:
        raw_name = claim.normalized_assertion.qualifiers.get("parameter")
        name = str(raw_name)
        parameters = self._parameters(path_item, operation)
        body_properties, body_required = self._body_schema(operation)
        located = parameters.get(name)
        exists = located is not None or name in body_properties
        required = bool(located and located.get("required")) or name in body_required
        expects_required = "requires" in claim.text.lower() or "required" in claim.text.lower()
        expects_optional = "optional" in claim.text.lower()
        if not exists:
            evidence = self.document.evidence(path, supports=False)
            return self._diverged(
                claim,
                f"OpenAPI does not declare parameter {name!r} for {method.upper()} {path}.",
                evidence,
            )
        if expects_required and not required:
            evidence = self.document.evidence(
                name, supports=False, fallback=self.document.line_for_key(path)
            )
            return self._diverged(
                claim,
                f"OpenAPI declares {name!r} for {method.upper()} {path}, but it is optional.",
                evidence,
            )
        if expects_optional and required:
            evidence = self.document.evidence(
                name, supports=False, fallback=self.document.line_for_key(path)
            )
            return self._diverged(
                claim,
                f"OpenAPI declares {name!r} for {method.upper()} {path}, but it is required.",
                evidence,
            )
        requirement = "required" if required else "optional"
        return self._verified(
            claim,
            f"OpenAPI declares {name!r} as {requirement} for {method.upper()} {path}.",
            self.document.evidence(name, supports=True, fallback=self.document.line_for_key(path)),
        )

    def _parameters(
        self, path_item: dict[str, Any], operation: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for source in (path_item.get("parameters", []), operation.get("parameters", [])):
            if not isinstance(source, list):
                continue
            for parameter in source:
                if isinstance(parameter, dict) and isinstance(parameter.get("name"), str):
                    result[parameter["name"]] = parameter
        return result

    def _body_schema(self, operation: dict[str, Any]) -> tuple[set[str], set[str]]:
        request_body = operation.get("requestBody", {})
        if not isinstance(request_body, dict):
            return set(), set()
        content = request_body.get("content", {})
        if not isinstance(content, dict):
            return set(), set()
        media_type = content.get("application/json", {})
        if not isinstance(media_type, dict):
            return set(), set()
        schema = media_type.get("schema", {})
        if not isinstance(schema, dict):
            return set(), set()
        reference = schema.get("$ref")
        if isinstance(reference, str):
            schema = self._resolve_local_reference(reference)
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        return (
            set(properties) if isinstance(properties, dict) else set(),
            set(required) if isinstance(required, list) else set(),
        )

    def _resolve_local_reference(self, reference: str) -> dict[str, Any]:
        if not reference.startswith("#/"):
            return {}
        node: Any = self.document.data
        for part in reference[2:].split("/"):
            if not isinstance(node, dict):
                return {}
            node = node.get(part.replace("~1", "/").replace("~0", "~"))
        return node if isinstance(node, dict) else {}

    def _closest_path(self, expected: str, method: str, paths: dict[str, Any]) -> str | None:
        candidates = [
            path
            for path, item in paths.items()
            if isinstance(path, str) and isinstance(item, dict) and method in item
        ]
        if not candidates:
            return None
        closest = max(
            candidates, key=lambda candidate: SequenceMatcher(None, expected, candidate).ratio()
        )
        ratio = SequenceMatcher(None, expected, closest).ratio()
        return closest if ratio >= 0.45 else None

    @staticmethod
    def _status_code(claim: Claim) -> int | None:
        value = claim.normalized_assertion.object
        if isinstance(value, int) and 100 <= value <= 599 and "http" in claim.text.lower():
            return value
        return None

    @staticmethod
    def _verified(claim: Claim, rationale: str, evidence: Evidence) -> VerificationResult:
        return VerificationResult(
            claim_id=claim.id,
            verdict=Verdict.VERIFIED,
            confidence=1.0,
            rationale=rationale,
            evidence=[evidence],
        )

    @staticmethod
    def _diverged(claim: Claim, rationale: str, evidence: Evidence) -> VerificationResult:
        return VerificationResult(
            claim_id=claim.id,
            verdict=Verdict.DIVERGED,
            confidence=1.0,
            rationale=rationale,
            evidence=[evidence],
            direction=DirectionAssessment(
                direction=Direction.UNDETERMINED,
                confidence=1.0,
                rationale=(
                    "The committed contract establishes the contradiction, but intent evidence "
                    "has not yet been evaluated."
                ),
                evidence=[evidence],
            ),
        )
