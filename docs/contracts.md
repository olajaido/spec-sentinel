# Core contracts

This document defines the stable boundary between extraction, verification, reporting, CI, and the dashboard. The executable form lives in `src/spec_sentinel/models.py`.

## Verdict semantics

| Verdict | Meaning | Minimum support |
| --- | --- | --- |
| `verified` | Implementation directly supports the claim | Direct code/spec evidence |
| `diverged` | Located implementation directly contradicts the claim | Direct contradictory evidence and confidence above threshold |
| `not_found` | A bounded, relevant search located no implementation | Claim evidence and complete search trail |
| `ambiguous` | Evidence is incomplete, conflicting, indirect, or budget-exhausted | Rationale and collected evidence/search trail |

`diverged` is not the fallback for uncertainty. Any result that fails its evidence or confidence invariant degrades to `ambiguous`.

## Direction semantics

Direction is assessed only after a divergence is established:

- `docs_stale`: evidence indicates code represents the current intended behaviour; a documentation patch may be proposed.
- `code_suspect`: tests, changelog, or other intent evidence suggests the documentation is right; no documentation patch.
- `undetermined`: direction cannot be safely inferred; no documentation patch.

## Evidence rules

Paths are repository-relative, cannot traverse above the scan root, and must resolve inside the read-only checkout. Line numbers are one-based. Evidence snippets are display conveniences, never authority; the referenced file and hash are authoritative.

## Report compatibility

Reports carry `schema_version`. Additive fields may be introduced in a minor schema revision. Removed fields or changed semantics require a major revision. CI and dashboard ingestion must reject unsupported major versions.
