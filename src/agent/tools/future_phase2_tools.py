"""Documented, inactive integration points for future Phase 2 tools."""

from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def search_engineering_confluence_and_specs(query: str, vehicle_program: str) -> dict:
    """Search engineering documentation after Phase 2 Confluence/RAG integration.

    Args:
        query: Technical question or search terms.
        vehicle_program: Vehicle program used to scope engineering materials.
    Returns:
        A future document-search result containing citations and excerpts.
    """
    logger.warning(
        "Confluence search requested before Phase 2 integration: query_characters=%d "
        "vehicle_program=%s",
        len(query),
        vehicle_program,
    )
    raise NotImplementedError("Confluence and specification retrieval is Phase 2.")


def query_signal_database_dbc_arxml(ecu_id: str, signal_or_message_name: str) -> dict:
    """Look up a signal or message in a future DBC/ARXML signal database.

    Args:
        ecu_id: ECU identifier associated with the signal database.
        signal_or_message_name: Signal or message to find.
    Returns:
        A future decoded signal definition and source reference.
    """
    logger.warning(
        "Signal database lookup requested before Phase 2 integration: ecu_id=%s "
        "query_characters=%d",
        ecu_id,
        len(signal_or_message_name),
    )
    raise NotImplementedError("DBC/ARXML parsing is Phase 2.")


def trigger_automated_test_and_triage_logs(
    booking_id: str, test_suite_id: str
) -> dict:
    """Trigger future automated execution and log triage for a booking.

    Args:
        booking_id: CIARA booking identifier.
        test_suite_id: Automated test suite identifier.
    Returns:
        A future execution job identifier and triage summary.
    """
    logger.warning(
        "Automated execution requested before Phase 2 integration: booking_id=%s "
        "test_suite_id=%s",
        booking_id,
        test_suite_id,
    )
    raise NotImplementedError("Automated test execution and triage is Phase 2.")
