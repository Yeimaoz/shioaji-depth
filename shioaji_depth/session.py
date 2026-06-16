"""Shioaji session login/logout helpers.

Reads credentials from explicit args or env vars. Accepted env names (first
non-empty wins):
- ``SHIOAJI_API_KEY``
- ``SHIOAJI_SECRET`` or ``SHIOAJI_SECRET_KEY`` (the latter matches shioaji's
  official documentation convention)

Optionally loads .env via python-dotenv at import time (safe no-op if no file).
Credentials are NEVER hard-coded here — they must be injected via env / .env.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv

import shioaji

logger = logging.getLogger(__name__)

load_dotenv()  # safe no-op if no .env file


class ShioajiAuthError(Exception):
    """Credentials missing or login failed."""


def login(
    api_key: str | None = None,
    secret: str | None = None,
) -> Any:
    """Create + log into a shioaji.Shioaji() session.

    Args:
        api_key: defaults to env SHIOAJI_API_KEY
        secret: defaults to env SHIOAJI_SECRET, falling back to SHIOAJI_SECRET_KEY

    Returns:
        Logged-in shioaji.Shioaji() instance (caller closes via ``logout``).

    Raises:
        ShioajiAuthError: if credentials are missing.
    """
    api_key = api_key or os.environ.get("SHIOAJI_API_KEY")
    # Accept both env names — SHIOAJI_SECRET_KEY matches the shioaji-doc convention.
    secret = (
        secret
        or os.environ.get("SHIOAJI_SECRET")
        or os.environ.get("SHIOAJI_SECRET_KEY")
    )
    if not api_key or not secret:
        raise ShioajiAuthError(
            "SHIOAJI_API_KEY + SHIOAJI_SECRET (or SHIOAJI_SECRET_KEY) required "
            "(pass args or set env vars)"
        )
    api = shioaji.Shioaji()
    api.login(api_key=api_key, secret_key=secret)
    logger.info("[shioaji-depth] logged in")
    return api


def logout(api: Any) -> None:
    """Log out of a shioaji session."""
    api.logout()
    logger.info("[shioaji-depth] logged out")
