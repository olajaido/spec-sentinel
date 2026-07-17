# Spec Sentinel

Spec Sentinel audits documentation claims against a repository's implementation. It prefers deterministic schema checks, uses bounded agentic investigation for behavioural claims, and abstains when the evidence is insufficient.

> Status: P0 core and the live pull-request gate are implemented. The demo produces 14 verified and exactly 4 diverged claims with no ambiguous results. The first external validation on Pact extracted 46 claims and found two evidence-backed documentation divergences; one additional unrelated repository remains.

## Repository layout

- `src/spec_sentinel/` — Python CLI and verification core.
- `tests/` — core tests.
- `examples/drifted-shop/` — deterministic FastAPI demo with seeded drift.
- `docs/` — product requirements, contracts, architecture, and implementation plan.

## Development

```bash
uv sync --all-extras
uv run pytest
uv run spec-sentinel --help
```

Run the deterministic path against the included fixture:

```bash
uv run spec-sentinel scan examples/drifted-shop --no-agentic
uv run spec-sentinel scan examples/drifted-shop --no-agentic --format json
uv run spec-sentinel fix examples/drifted-shop --no-agentic
uv run spec-sentinel delta baseline.json current.json --format md
```

For behavioural verification, create an API key from the [OpenAI API key page](https://platform.openai.com/api-keys), set `OPENAI_API_KEY` in the process environment or in a Git-ignored `.env` file at the scanned repository root, then add `--agentic`. Environment variables take precedence over `.env`. The default model is configured in `spec-sentinel.yml` and can be changed without modifying code.
When the secrets file lives elsewhere, pass it explicitly—for this monorepo fixture: `uv run spec-sentinel scan examples/drifted-shop --agentic --env-file .env`.

CI must use `--no-load-dotenv` so a pull-request checkout cannot supply client configuration such as an alternate API endpoint. The bundled Action sets this automatically.

A README is optional. Configure any Markdown documentation paths through `docs` in `spec-sentinel.yml`. If no documentation files—or no concrete, testable claims—are found, terminal and JSON reports emit an explicit warning, and PR comments show an audit warning instead of a misleading green result.

The demo contains 18 extracted claims. Ten route through committed OpenAPI, where eight verify and two intentionally diverge. The remaining eight route to the behavioural agent, where six verify and two intentionally diverge. Three `docs_stale` findings receive safe unified diffs; the `code_suspect` retry finding never receives a patch.

The verified live run completed in about 39 seconds. An unchanged repeat used eight cached agentic verdicts, made zero model requests, and completed in 0.024 seconds. The demo application tests pass with the intentionally suspect retry behaviour marked as an expected failure.

## GitHub Action

The composite [Action](./action.yml) runs on both `push` to the default branch and `pull_request`:

- A default-branch push stores a complete baseline keyed to that commit.
- A pull request restores the exact base-commit baseline or performs a full cold-cache baseline scan.
- The Action compares complete artifacts and updates one persistent comment with only newly broken and resolved claims.
- `fail-on-new-divergence: "true"` makes new drift fail the check after the comment is published.

Add `OPENAI_API_KEY` as a GitHub Actions repository secret and grant only `contents: read` and `pull-requests: write`. A complete trusted-checkout example is included at [`.github/workflows/spec-sentinel.yml`](./.github/workflows/spec-sentinel.yml). When consuming the published Action from another repository, pin it to a full commit SHA:

```yaml
- uses: OWNER/spec-sentinel@FULL_COMMIT_SHA
  with:
    github-token: ${{ github.token }}
    fail-on-new-divergence: "false"
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

Do not switch the workflow to `pull_request_target` to expose secrets to forked pull requests. GitHub does not provide Actions secrets to ordinary fork PRs; those runs need a separately designed trusted service if agentic verification is required.

The scanner treats every repository as hostile input. It does not execute target code, follow symlinks, or expose a general-purpose shell to the verification agent. The workflow installs executable Action code from the trusted base revision and treats the pull-request checkout only as evidence.
