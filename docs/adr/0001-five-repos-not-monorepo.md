# 0001. Five separate repos, not a monorepo

* **Status:** accepted
* **Date:** 2026-05-26
* **Deciders:** @petrefiedthunder

## Context and problem statement

Sentinel is a product with sharply different audiences for each piece of code:

- **Python SDK** (`sentinel-sdk`) — for AI-agent developers; published to PyPI
- **TypeScript SDK** (`sentinel-sdk-js`) — same product, different ecosystem; published to npm
- **Backend API** (`sentinel-api`) — internal infrastructure; deployed to Railway
- **Dashboard** (`sentinel-dashboard`) — auth-gated tenant UI; deployed to Vercel
- **Marketing site** (`oversight-landing`) — public homepage + docs; deployed to Vercel
- **Examples** (`sentinel-examples`) — runnable code samples; for prospects to clone

Should these live in one repo (a monorepo with workspaces / Turborepo / Nx) or five?

## Decision drivers

* **Audience separation.** SDK users `git clone sentinel-sdk` expecting a focused codebase. They don't want to download a 50MB Next.js dashboard.
* **Independent versioning.** Python SDK 0.1.9, TS SDK 0.1.0, dashboard rolling — these don't move together and shouldn't be pinned to a single bump.
* **Independent CI/CD.** Each repo has different test matrix, different deploy target, different secrets. Monorepo CI is a path-filter dance.
* **Public-vs-private boundary.** SDKs + examples + landing are PUBLIC. API + dashboard could go either way (currently public, may go private). Monorepo forces the lowest common denominator on visibility.
* **PR review surface.** A PR that only touches the dashboard shouldn't trigger SDK reviewers (and vice versa).
* **Open-source contribution surface.** Outside contributors expect to fork the SDK repo, not a 200-package monorepo. The barrier to a drive-by PR matters at our stage.
* **Cost of cross-repo type drift.** This IS a real cost — handled separately in [ADR-0002](#-adr-0002) (HMAC tokens) and a future ADR on OpenAPI client generation.

## Considered options

* **A. Five repos (chosen)**
* **B. Monorepo with pnpm workspaces + Turborepo**
* **C. Hybrid: two repos — `sentinel-sdks` (Python + TS) and `sentinel-platform` (API + dashboards + landing)**

## Decision outcome

**Chosen option: A. Five repos**, because the cost of audience confusion and CI complexity in a monorepo at our stage (solo dev, design-partner phase) outweighs the type-drift cost that monorepos solve. We'll mitigate drift via OpenAPI client generation (future ADR) rather than physical repo merging.

### Positive consequences

* Each repo's README, CI, contributors, and issue tracker is focused
* Independent semver per package
* Public repos stay small + crawlable
* New contributors can fork one repo without understanding the full system
* PyPI / npm Trusted Publishing configs are 1:1 with repos

### Negative consequences (the trade-off we accepted)

* Type drift between API ↔ dashboard ↔ JS SDK is a real risk. Mitigated by generating types from `/openapi.json` (see ADR-0004 to be written).
* A change that spans repos (e.g. "add new webhook event type") requires N PRs across N repos.
* Cross-repo refactors need either git submodules or careful coordination.
* No shared lint/format config — we duplicate `ruff.toml` etc. across Python repos.

## Links

* Related code: `ARCHITECTURE.md` at the workspace root
* All repos: https://github.com/PetrefiedThunder
