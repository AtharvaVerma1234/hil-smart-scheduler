"""Safe parsing helpers for source CSV values."""

import re
from typing import Any

import pandas as pd


def natural_sort_key(value: Any) -> tuple:
    """Return a case-insensitive natural-sort key for an arbitrary identifier."""
    parts = re.split(r"(\d+)", str(value).strip())
    return tuple(int(token) if token.isdigit() else token.casefold() for token in parts)


def resolve_rig_id(
    raw_rig_id: Any,
    valid_rig_ids: set[str] | list[str] | None = None,
) -> str:
    """Resolve a user-supplied rig identifier against the active rig catalog."""
    raw = str(raw_rig_id).strip()
    if not raw:
        return ""
    if valid_rig_ids is None:
        match = re.fullmatch(r"([A-Za-z]+_?)0*(\d+)", raw)
        if match:
            return f"{match.group(1).upper()}{int(match.group(2))}"
        return raw.upper()

    valid_ids = list(valid_rig_ids)
    by_casefold = {rig_id.casefold(): rig_id for rig_id in valid_ids}

    def zero_stripped(value: str) -> str:
        return re.sub(r"(?<=[A-Z_-])0+(\d+)", r"\1", value.upper())

    by_normalized = {
        zero_stripped(rig_id): rig_id
        for rig_id in sorted(valid_ids, key=len, reverse=True)
    }
    direct = by_casefold.get(raw.casefold())
    if direct:
        return direct
    direct = by_normalized.get(zero_stripped(raw))
    if direct:
        return direct

    padded_variants = sorted(
        valid_ids,
        key=len,
        reverse=True,
    )
    for candidate in padded_variants:
        canonical_form = zero_stripped(candidate)
        flexible_form = re.sub(
            r"\d+",
            lambda match: rf"0*{match.group()}",
            re.escape(canonical_form),
        )
        match = re.search(
            rf"(?<![A-Z0-9]){flexible_form}(?![A-Z0-9])",
            raw,
            re.IGNORECASE,
        )
        if match:
            return candidate
    return ""


def parse_pipe_list(val: Any) -> list[str]:
    """Split a pipe-delimited cell, treating null and NONE values as empty."""
    if pd.isna(val):
        return []
    value = str(val).strip()
    if value.upper() in ("", "NONE", "NAN"):
        return []
    return [item.strip() for item in value.split("|") if item.strip()]
