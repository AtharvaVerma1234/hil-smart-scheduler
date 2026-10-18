"""Schemas for conversational session state and staged bookings."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class BookingCartItem(BaseModel):
    """One selected availability window with its editable booking interval."""

    rig_id: str
    date: str
    start_time: str
    end_time: str
    orig_start_time: str
    orig_end_time: str
    window_type: str
    rig_details: str = ""
    selected: bool = False


class BookingCart(BaseModel):
    """Validated shape for the UI's pending selections."""

    items: list[BookingCartItem] = Field(default_factory=list)
    target_duration_hours: float = 0.0
    slot_type: Optional[str] = None


class SessionSnapshot(BaseModel):
    """Serializable subset of Streamlit state useful for diagnostics."""

    messages: list[dict[str, Any]] = Field(default_factory=list)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    candidate_slots: list[dict[str, Any]] = Field(default_factory=list)
    target_duration_hours: float = 0.0
