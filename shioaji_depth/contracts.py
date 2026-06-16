"""Resolve user-given TAIFEX futures shortcodes to shioaji.Contract instances.

Maps common short symbols (MTX / TXF / TMF) to the rolling front-month contract
in ``api.Contracts.Futures.{group}.{group}R1`` (the shioaji standard rolling key).

Generic: no orchestration policy, no fixed symbol universe — callers pass the
shortcodes they want.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Short symbol -> primary contract group in api.Contracts.Futures.
_FUT_SHORTCODE_MAP = {
    "MTX": "MXF",   # 小台 (Mini-TAIEX)
    "TXF": "TXF",   # 大台 (TAIEX)
    "TMF": "TMF",   # 微台 (Micro-TAIEX)
}


def resolve_contract(api: Any, contract: str) -> Any:
    """Resolve a contract string to a shioaji.Contract instance.

    Strategy:
    - Shortcode (MTX/TXF/TMF): pick the rolling front-month from
      ``api.Contracts.Futures.{MXF/TXF/TMF}``. Prefers the explicit rolling key
      ``{group}R1`` (MXFR1/TXFR1/TMFR1 — shioaji standard).
    - Explicit delivery code (e.g. MXFM4): nested lookup by the 3-char prefix.

    Raises:
        ValueError: if the contract cannot be resolved.
    """
    fut = getattr(api.Contracts, "Futures", None)
    if fut is not None:
        if contract in _FUT_SHORTCODE_MAP:
            group_key = _FUT_SHORTCODE_MAP[contract]
            group = getattr(fut, group_key, None)
            if group is not None:
                # Prefer explicit rolling key (R1 = front-month rolling).
                rolling_key = group_key + "R1"
                # group may be dict-like or attr-accessor — try both.
                if isinstance(group, dict) and rolling_key in group:
                    return group[rolling_key]
                if hasattr(group, "items") and rolling_key in group:
                    return group[rolling_key]
                if hasattr(group, rolling_key):
                    return getattr(group, rolling_key)
                # Fallback: iterate values (dict iteration unordered — last resort).
                if isinstance(group, dict):
                    for _k, v in group.items():
                        return v
                if hasattr(group, "items"):
                    for _k, v in group.items():
                        return v
                return group
        # Try explicit delivery code (e.g. MXFM4).
        prefix = contract[:3]
        if hasattr(fut, prefix):
            group = getattr(fut, prefix)
            if hasattr(group, contract):
                return getattr(group, contract)
            if isinstance(group, dict) and contract in group:
                return group[contract]

    raise ValueError(f"could not resolve contract: {contract!r}")
