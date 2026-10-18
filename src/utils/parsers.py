"""Safe parsing helpers for source CSV values."""

from typing import Any

import pandas as pd


def parse_pipe_list(val: Any) -> list[str]:
    """Split a pipe-delimited cell, treating null and NONE values as empty."""
    if pd.isna(val):
        return []
    value = str(val).strip()
    if value.upper() in ("", "NONE", "NAN"):
        return []
    return [item.strip() for item in value.split("|") if item.strip()]
