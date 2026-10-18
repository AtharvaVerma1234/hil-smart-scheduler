"""CSV-backed repository for Phase 1."""

import re
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import settings
from src.repositories.base import AbstractHILRepository
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class CSVHILRepository(AbstractHILRepository):
    """Read the ground-truth CSVs and append confirmed bookings."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else settings.DATA_RAW_DIR
        self._paths = {
            "rigs": self.data_dir / "rig_capabilities.csv",
            "features": self.data_dir / "feature_requirements.csv",
            "programs": self.data_dir / "vehicle_program_ecus.csv",
            "bookings": self.data_dir / "ciara_bookings.csv",
        }
        logger.debug(
            "CSV repository initialized: data_dir=%s datasets=%s",
            self.data_dir,
            sorted(self._paths),
        )

    def _read(self, name: str) -> pd.DataFrame:
        path = self._paths[name]
        if not path.is_file():
            logger.error("Required CSV is missing: dataset=%s path=%s", name, path)
            raise FileNotFoundError(f"Required HIL data file does not exist: {path}")
        try:
            frame = pd.read_csv(path, dtype=str, keep_default_na=True)
        except Exception:
            logger.exception("Failed to parse CSV dataset=%s path=%s", name, path)
            raise
        logger.info(
            "CSV dataset loaded: dataset=%s path=%s rows=%d columns=%d",
            name,
            path,
            len(frame),
            len(frame.columns),
        )
        logger.debug("CSV schema: dataset=%s columns=%s", name, list(frame.columns))
        return frame

    def get_all_rigs(self) -> pd.DataFrame:
        return self._read("rigs")

    def get_feature_requirements(self) -> pd.DataFrame:
        return self._read("features")

    def get_vehicle_program_ecus(self) -> pd.DataFrame:
        return self._read("programs")

    def get_bookings(self) -> pd.DataFrame:
        return self._read("bookings")

    def append_bookings(self, new_bookings: list[dict[str, Any]]) -> list[str]:
        if not new_bookings:
            logger.warning("Ignoring empty booking append request.")
            return []
        path = self._paths["bookings"]
        logger.info("Appending bookings: requested_count=%d path=%s", len(new_bookings), path)
        existing = self._read("bookings")
        numbers = [
            int(match.group(1))
            for value in existing.get("Booking_ID", pd.Series(dtype=str)).dropna()
            if (match := re.fullmatch(r"BK_(\d+)", str(value).strip()))
        ]
        next_number = max(numbers, default=0) + 1
        booking_ids = [f"BK_{next_number + index}" for index in range(len(new_bookings))]
        rows = []
        for booking_id, booking in zip(booking_ids, new_bookings):
            rows.append(
                {
                    "Booking_ID": booking_id,
                    "Rig_ID": booking["Rig_ID"],
                    "Date": booking["Date"],
                    "Slot_Start_Time": booking["Slot_Start_Time"],
                    "Slot_End_Time": booking["Slot_End_Time"],
                    "Slot_Type": booking["Slot_Type"],
                    "Booked_By_User": booking["Booked_By_User"],
                }
            )
        updated = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
        try:
            updated.to_csv(path, index=False)
        except Exception:
            logger.exception(
                "Failed to persist bookings: path=%s attempted_count=%d",
                path,
                len(rows),
            )
            raise
        logger.info(
            "Bookings persisted: added_count=%d booking_ids=%s total_rows=%d",
            len(booking_ids),
            booking_ids,
            len(updated),
        )
        return booking_ids
