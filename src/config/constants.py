"""Shared enumerations and scheduling thresholds."""

from enum import Enum


class SlotType(str, Enum):
    """Supported CIARA booking purposes."""

    MANUAL_TESTING = "MANUAL_TESTING"
    TEST_PROVEOUT = "TEST_PROVEOUT"
    AUTOMATED_END_TO_END_EXECUTION = "AUTOMATED_END_TO_END_EXECUTION"
    RIG_MAINTENANCE = "RIG_MAINTENANCE"
    DEBUGGING = "DEBUGGING"
    TRIAGING = "TRIAGING"


class PlatformType(str, Enum):
    """Supported HIL rig platforms."""

    DSPACE = "dSPACE"
    VECTOR = "Vector"
    NI = "NI"


MIN_SLOT_DURATION_HOURS = 0.5
COMPATIBILITY_CUTOFF_PERCENT = 50.0
FALLBACK_TOP_K_RIGS = 4
EXTENDED_SHIFT_DELTA_HOURS = 2
