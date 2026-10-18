"""Abstract repository contract for HIL data sources."""

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class AbstractHILRepository(ABC):
    """Contract shared by CSV and future CIARA API repositories."""

    @abstractmethod
    def get_all_rigs(self) -> pd.DataFrame:
        """Return all rig capability records."""

    @abstractmethod
    def get_feature_requirements(self) -> pd.DataFrame:
        """Return all feature-to-ECU requirement records."""

    @abstractmethod
    def get_vehicle_program_ecus(self) -> pd.DataFrame:
        """Return applicable ECU records for each vehicle program."""

    @abstractmethod
    def get_bookings(self) -> pd.DataFrame:
        """Return all existing CIARA bookings."""

    @abstractmethod
    def append_bookings(self, new_bookings: list[dict[str, Any]]) -> list[str]:
        """Persist bookings and return their assigned identifiers."""
