"""Typed domain models for rigs, available slots, and bookings."""

from datetime import date, time
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.config.constants import PlatformType, SlotType


class Rig(BaseModel):
    """A hardware-in-the-loop rig and its ECU configurations."""

    model_config = ConfigDict(extra="allow")

    rig_id: str = Field(alias="Rig_ID")
    vehicle_program: str = Field(alias="Vehicle_Program")
    domain: str = Field(alias="Rig_Domain")
    platform: PlatformType = Field(alias="Rig_Platform")
    engineer: str = Field(alias="Rig_Engineer")
    real_ecus: list[str] = Field(default_factory=list, alias="Real_Connected_Components")
    can_sim_ecus: list[str] = Field(default_factory=list, alias="CAN_Sim_ECUs")
    eth_sim_ecus: list[str] = Field(default_factory=list, alias="Eth_Sim_ECUs")


class Slot(BaseModel):
    """A free interval available for selection and later booking."""

    rig_id: str
    date: date
    start_time: time
    end_time: time
    duration_hrs: float
    window_type: str
    orig_start_time: Optional[time] = None
    orig_end_time: Optional[time] = None
    rig_details: str = ""


class Booking(BaseModel):
    """A booking stored in the CIARA schedule."""

    booking_id: Optional[str] = None
    rig_id: str
    date: date
    slot_start_time: time
    slot_end_time: time
    slot_type: SlotType
    booked_by_user: str
