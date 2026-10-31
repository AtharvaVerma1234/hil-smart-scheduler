"""Data access implementations and configured repository factory."""

import os

from src.repositories.base import AbstractHILRepository
from src.repositories.ciara_api_repository import CiaraAPIRepository
from src.repositories.csv_repository import CSVHILRepository


def get_repository() -> AbstractHILRepository:
    """Return the configured HIL repository implementation."""
    source = os.environ.get("HIL_DATA_SOURCE", "csv").lower()
    if source == "ciara_api":
        return CiaraAPIRepository()
    return CSVHILRepository()
