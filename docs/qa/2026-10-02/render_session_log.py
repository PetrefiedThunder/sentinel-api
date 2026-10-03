"""Render the immutable per-group command ledgers into a readable QA session log."""

import json
from datetime import UTC, datetime
from pathlib import Path

root = Path(__file__).resolve().parent
entries = []
for ledger in root.glob("*-commands.jsonl"):
    entries.extend(json.loads(line) for line in ledger.read_text().splitlines() if line)
entries.sort(key=lambda entry: entry["started_utc"])
bootstrap = json.loads((root / "artifacts/bootstrap.json").read_text())
lines = [
    "# UTC session log — 2026-10-02 QA sweep",
    "",
    "PR: opened by orchestrator",
    "CI status: pending at time of writing",
    "",
    "The requested folder date is the Los Angeles date; execution occurred on October 3 UTC. "
    "Each entry below records a shell command or compound command, start/end UTC, exit status, "
    "and a sanitized output artifact. Source edits made with apply_patch are recorded in the "
    "pass narratives rather than represented as shell commands. The JSONL ledgers are authoritative "
    "and may include the completion record of this rendering command after this page is written.",
    "",
    "## Bootstrap before the command recorder",
    "",
    f"Recorded retrospectively at {bootstrap['timestamp_utc']}. Exact individual execution "
    "timestamps were not captured; these are not invented execution times.",
    "",
]
for label, command, outcome in bootstrap["commands"]:
    lines += [f"- **{label}:** `{command}` — {outcome}."]
lines += [
    "",
    "UX also ran a standalone pwd before 01:35:42Z; it returned the expected checkout. "
    "A backend subagent's first wrapper invocation used an unsupported backend-security "
    "group and was rejected before its inner command ran; its next successful entry records this. "
    "A lead nested-heredoc quoting failure is recorded below with an approximate timestamp.",
    "",
    "## Test sessions, charters and non-shell actions",
    "",
    "- Backend BE-C1/BE-C2: see [BACKEND-LOG.md](BACKEND-LOG.md) for UTC charter bounds, "
    "auth/permissions matrix, OWASP review and bug reproductions.",
    "- Frontend FE-C1/FE-C2: see [FRONTEND-LOG.md](FRONTEND-LOG.md) for contract exploration, "
    "baseline comparison, boundary inputs and independent negative controls.",
    "- UX-C1/C2/C3: see [UX-LOG.md](UX-LOG.md) for setup reproduction, browser engines, "
    "axe, keyboard/semantics, viewports, synthetic states and Nielsen review.",
    "- Independent gate: [GATE-LOG.md](GATE-LOG.md). Tests were refined to narrow xfails "
    "and expose each contract gap independently; product code was not changed.",
    "- Around 01:37 UTC, apply_patch wrote PLAN.md and the safe pytest bootstrap after a "
    "shell quoting failure. Subsequent apply_patch edits added command-recorder lazy-fetch "
    "protection and this renderer. New test and UX harness edits are described in group logs.",
    "- Around 01:40 UTC, the lead used view_image to independently inspect desktop and mobile "
    "documentation screenshots. UX captures and state screenshots are referenced in UX-LOG.md.",
    "",
    "## Interpretation of failed commands",
    "",
    "Expected-failure negative controls intentionally exit 1. No-match rg exits and missing "
    "optional tools/paths are discovery outcomes, not product failures. The first npm cache "
    "attempt and UTF-8 docs adapter attempts failed; successful retries are preserved separately. "
    "Mypy reports five existing diagnostics. A stdin secret scan lost path allowlist context "
    "and flagged an existing synthetic fixture. A history secret scan exited zero despite "
    "fatal partial-clone/object-store errors and zero scanned commits; it is unverified. "
    "The complete outcomes, including these dead ends, follow.",
    "",
    f"## Command ledger ({len(entries)} completed records at rendering)",
    "",
]
for index, entry in enumerate(entries, 1):
    lines += [
        f"### {index:03d} — {entry['started_utc']} — {entry['group']}: {entry['label']}",
        "",
        f"End: {entry.get('ended_utc', 'not captured')}; "
        f"duration: {entry.get('duration_seconds', 'not captured')} seconds; "
        f"exit: **{entry['exit_code']}**.",
        "",
        "```sh",
        entry["command"],
        "```",
        "",
    ]
    if entry.get("artifact"):
        lines += [f"Outcome/output: [{entry['artifact']}]({entry['artifact']}).", ""]
    if entry.get("outcome"):
        lines += [entry["outcome"], ""]
lines += [
    "## Rendering completion",
    "",
    f"{datetime.now(UTC).isoformat()}: rendered this page from all completed group ledgers. "
    "The generating command is python3 docs/qa/2026-10-02/render_session_log.py; its outcome "
    "is this updated page. Its wrapper completion record is appended to lead-commands.jsonl "
    "after the renderer returns.",
]
(root / "SESSION-LOG.md").write_text("\n".join(lines) + "\n")
print(f"Rendered SESSION-LOG.md from {len(entries)} completed command records.")
