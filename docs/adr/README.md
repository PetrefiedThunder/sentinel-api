# Architecture Decision Records

Each ADR documents a single significant decision: context, options considered, choice, and trade-offs accepted. Follow the [MADR](https://adr.github.io/madr/) format.

## Why we keep these

Most architecture context lives in commit messages or someone's head. ADRs make the **why** behind a decision findable later, when "someone" has moved on or forgotten.

## How to add one

```bash
# Find the next number
ls docs/adr/ | grep -E '^[0-9]{4}-' | sort | tail -1

# Copy the template
cp docs/adr/0000-template.md docs/adr/NNNN-<kebab-title>.md

# Fill in. Status starts as "proposed".
# After team / self review → mark "accepted" and merge.
```

## Status lifecycle

- **proposed** — drafted, not yet decided
- **accepted** — the chosen direction
- **deprecated** — superseded but kept for history (link forward to the replacement)
- **rejected** — considered, declined, with reasoning

## Records

| # | Title | Status |
|---|---|---|
| 0001 | Why 5 repos instead of a monorepo | accepted |
| 0002 | HMAC-signed magic-link approval tokens | accepted |
| 0003 | Webhook retry policy: 3 attempts, exponential backoff | accepted |
