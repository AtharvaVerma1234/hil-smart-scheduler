"""Phase 2 repository boundary for the live CIARA REST API."""

from typing import Any

import pandas as pd

from src.repositories.base import AbstractHILRepository
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class CiaraAPIRepository(AbstractHILRepository):
    """CIARA API adapter contract; live HTTP transport is intentionally Phase 2."""

    def get_all_rigs(self) -> pd.DataFrame:
        """Map the future CIARA rig endpoint response to the repository schema."""
        logger.warning("CIARA API rig retrieval requested before Phase 2 API integration.")
        raise NotImplementedError("Live CIARA rig endpoint integration belongs to Phase 2.")

    def get_feature_requirements(self) -> pd.DataFrame:
        """Feature requirements remain a separately provisioned data source."""
        logger.warning("CIARA API feature retrieval requested before Phase 2 integration.")
        raise NotImplementedError("Feature API integration belongs to Phase 2.")

    def get_vehicle_program_ecus(self) -> pd.DataFrame:
        """Vehicle program topology remains a separately provisioned data source."""
        logger.warning("CIARA API topology retrieval requested before Phase 2 integration.")
        raise NotImplementedError("Topology API integration belongs to Phase 2.")

    def get_bookings(self) -> pd.DataFrame:
        """GET /api/v1/bookings will map its JSON records to the CSV schema."""
        logger.warning("GET /api/v1/bookings requested; live API integration is Phase 2.")
        raise NotImplementedError("GET /api/v1/bookings is a Phase 2 integration point.")

    def append_bookings(self, new_bookings: list[dict[str, Any]]) -> list[str]:
        """POST /api/v1/bookings will persist records and return server IDs."""
        logger.warning(
            "POST /api/v1/bookings requested: count=%d; live API integration is Phase 2.",
            len(new_bookings),
        )
        raise NotImplementedError("POST /api/v1/bookings is a Phase 2 integration point.")
