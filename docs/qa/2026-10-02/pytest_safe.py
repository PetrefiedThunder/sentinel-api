#!/usr/bin/env python3
"""Run QA pytest without .env reads or network sockets, including localhost."""

import sys
from pathlib import Path

from pydantic_settings import BaseSettings

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
_original_init = BaseSettings.__init__


def _without_env_file(self, **values):
    values["_env_file"] = None
    _original_init(self, **values)


BaseSettings.__init__ = _without_env_file

import pytest  # noqa: E402

raise SystemExit(pytest.main(["--disable-socket", "--allow-unix-socket", *sys.argv[1:]]))
