#!/usr/bin/env python3
"""QA-only command recorder. Run from repository root; never pass credentials."""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--group", required=True, choices=["backend", "frontend", "ux", "lead", "gate"])
parser.add_argument("--label", required=True)
parser.add_argument("--timeout", type=int, default=180)
parser.add_argument("command")
args = parser.parse_args()
root = Path(__file__).resolve().parent
stamp = datetime.datetime.now(datetime.UTC)
slug = re.sub(r"[^a-z0-9]+", "-", args.label.lower()).strip("-")
name = f"{args.group}-{stamp.strftime('%H%M%S%f')}-{slug}.txt"
artifact = root / "artifacts" / name


def redact(value):
    value = re.sub(
        r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
        "[REDACTED]",
        value,
        flags=re.S,
    )
    value = re.sub(
        r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?(?:bearer\s+)?)[^\s\"',}]+",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(
        r"(?:sk_live_|rk_live_|sk_test_|ghp_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]+",
        "[REDACTED]",
        value,
    )
    value = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/:@]+:[^\s/@]+@", r"\1[REDACTED]@", value)
    value = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED]", value)
    return value


entry = {
    "started_utc": stamp.isoformat(),
    "group": args.group,
    "label": args.label,
    "command": redact(args.command),
    "artifact": f"artifacts/{name}",
}
start = time.monotonic()
# No inherited provider credentials or automatic environment-file reads.
env = {
    k: v
    for k, v in os.environ.items()
    if k
    in {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "PW_TEST_CONNECT_WS_ENDPOINT",
        "VIRTUAL_ENV",
        "UV_CACHE_DIR",
    }
}
try:
    # Partial clones may otherwise fetch missing objects during read-only scans.
    env["GIT_NO_LAZY_FETCH"] = "1"
    result = subprocess.run(
        args.command,
        shell=True,
        executable="/bin/zsh",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=args.timeout,
        env=env,
    )
    output, code = result.stdout, result.returncode
except subprocess.TimeoutExpired as exc:
    output = exc.stdout or ""
    if isinstance(output, bytes):
        output = output.decode(errors="replace")
    output += "\nQA TIMEOUT\n"
    code = 124
entry.update(
    ended_utc=datetime.datetime.now(datetime.UTC).isoformat(),
    duration_seconds=round(time.monotonic() - start, 3),
    exit_code=code,
)
output = redact(output)
artifact.write_text(output)
with (root / f"{args.group}-commands.jsonl").open("a") as stream:
    stream.write(json.dumps(entry) + "\n")
print(output, end="")
print(f"\nQA_LOG: {entry['artifact']} | exit={code}")
sys.exit(code)
