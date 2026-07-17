"""Static intent signals used to gate documentation patch generation."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from spec_sentinel.models import (
    Claim,
    Direction,
    DirectionAssessment,
    Evidence,
    EvidenceKind,
    SourceLocation,
    Verdict,
    VerificationResult,
)

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


@dataclass(frozen=True)
class PythonRoute:
    method: str
    path: str
    file: str
    line: int
    parameters: frozenset[str]
    snippet: str


def index_python_routes(root: Path, files: list[Path]) -> dict[tuple[str, str], PythonRoute]:
    root = root.resolve()
    routes: dict[tuple[str, str], PythonRoute] = {}
    for file in files:
        if file.suffix != ".py":
            continue
        try:
            source = file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            parameters = frozenset(argument.arg for argument in node.args.args)
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not decorator.args:
                    continue
                function = decorator.func
                if (
                    not isinstance(function, ast.Attribute)
                    or function.attr.lower() not in HTTP_METHODS
                ):
                    continue
                route_path = decorator.args[0]
                if not isinstance(route_path, ast.Constant) or not isinstance(
                    route_path.value, str
                ):
                    continue
                line = getattr(decorator, "lineno", node.lineno)
                route = PythonRoute(
                    method=function.attr.lower(),
                    path=route_path.value,
                    file=file.resolve().relative_to(root).as_posix(),
                    line=line,
                    parameters=parameters,
                    snippet=lines[line - 1].strip(),
                )
                routes[(route.method, route.path)] = route
    return routes


def assess_mechanical_direction(
    claim: Claim,
    result: VerificationResult,
    root: Path,
    scope_files: list[Path],
) -> VerificationResult:
    if result.verdict is not Verdict.DIVERGED:
        return result
    method = claim.normalized_assertion.qualifiers.get("method")
    path = claim.normalized_assertion.qualifiers.get("path")
    if not isinstance(method, str) or not isinstance(path, str):
        return result
    routes = index_python_routes(root, scope_files)
    route: PythonRoute | None = None
    signal = ""
    parameter = claim.normalized_assertion.qualifiers.get("parameter")
    if isinstance(parameter, str):
        candidate = routes.get((method.lower(), path))
        if candidate is not None and parameter not in candidate.parameters:
            route = candidate
            signal = (
                f"The committed OpenAPI contract and the {method.upper()} {path} handler both "
                f"omit parameter {parameter!r}."
            )
    else:
        for evidence in result.evidence:
            alternative = evidence.snippet.strip().strip("'\"").removesuffix(":")
            candidate = routes.get((method.lower(), alternative))
            if candidate is not None:
                route = candidate
                signal = (
                    f"The committed OpenAPI contract and route code both expose "
                    f"{method.upper()} {alternative}, while the documented path is absent."
                )
                break
    if route is None:
        return result
    code_evidence = Evidence(
        kind=EvidenceKind.CODE,
        location=SourceLocation(file=route.file, line=route.line),
        snippet=route.snippet,
        supports=False,
    )
    combined = [*result.evidence, code_evidence]
    return result.model_copy(
        update={
            "evidence": combined,
            "direction": DirectionAssessment(
                direction=Direction.DOCS_STALE,
                confidence=0.95,
                rationale=signal,
                evidence=combined,
            ),
        }
    )
