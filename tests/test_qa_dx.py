"""Executable checks for the public, local-only onboarding examples."""

import json
import re
from pathlib import Path

import pytest

from app.schemas import ApprovalCreate, DecisionRequest, TenantSignup

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("index", "schema"),
    [(0, TenantSignup), (1, ApprovalCreate), (2, DecisionRequest)],
)
def test_readme_quickstart_payload_matches_public_model(index, schema):
    examples = re.findall(r"-d '({.*?})'", (ROOT / "README.md").read_text(), re.DOTALL)
    payload = schema.model_validate(json.loads(examples[index]))
    if isinstance(payload, TenantSignup):
        assert payload.mode == "test", "The local quickstart must suppress real notifications"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="UX-002: CONTRIBUTING names a nonexistent test file",
)
def test_contributing_single_file_test_example_exists():
    paths = re.findall(r"pytest\s+(tests/[\w./-]+\.py)", (ROOT / "CONTRIBUTING.md").read_text())
    if not paths:
        pytest.fail("Expected an executable single-file pytest example")
    for path in paths:
        assert (ROOT / path).is_file(), f"Documented test file does not exist: {path}"
