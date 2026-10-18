"""Phase 1 topology inspection and deterministic rig matching tools."""

from typing import Optional

import streamlit as st

from src.agent.tools.registry import register_tool
from src.repositories.csv_repository import CSVHILRepository
from src.services.capability_matcher import CapabilityMatcherService
from src.utils.parsers import parse_pipe_list


@register_tool
def inspect_topology_and_features(
    feature_name: Optional[str] = None,
    vehicle_program: Optional[str] = None,
) -> dict:
    """Inspect program ECUs and feature requirements from ground-truth CSVs.

    Use ONLY when the user asks a pure informational question about ECU
    topology or feature definitions without requesting rig matching or slot
    availability. Do NOT call this before `match_rigs_by_criteria`, because
    `match_rigs_by_criteria` already inspects feature requirements and program
    topology internally.

    Args:
        feature_name: Optional feature identifier, for example FEATURE_1.
        vehicle_program: Optional vehicle program identifier to narrow results.
    Returns:
        Applicable ECU lists and matching Real, CAN simulation, and Ethernet
        simulation feature requirements.
    """
    repository = CSVHILRepository()
    result: dict = {"vehicle_program_ecus": [], "feature_requirements": []}
    programs = repository.get_vehicle_program_ecus().fillna("")
    if vehicle_program:
        programs = programs[
            programs["Vehicle_Program"].str.casefold() == vehicle_program.casefold()
        ]
    for _, row in programs.iterrows():
        result["vehicle_program_ecus"].append(
            {
                "vehicle_program": row["Vehicle_Program"],
                "applicable_ecus": parse_pipe_list(row["Applicable_ECUs"]),
            }
        )
    requirements = repository.get_feature_requirements().fillna("")
    if feature_name:
        requirements = requirements[
            requirements["Feature_Name"].str.casefold() == feature_name.casefold()
        ]
    if vehicle_program:
        requirements = requirements[
            requirements["Vehicle_Program"].str.casefold() == vehicle_program.casefold()
        ]
    for _, row in requirements.iterrows():
        result["feature_requirements"].append(
            {
                "feature_name": row["Feature_Name"],
                "vehicle_program": row["Vehicle_Program"],
                "real_ecus_required": parse_pipe_list(row["Real_ECUs_Required"]),
                "can_sim_needed": parse_pipe_list(row["CAN_Sim_Needed"]),
                "eth_sim_needed": parse_pipe_list(row["Eth_Sim_Needed"]),
            }
        )
    return result


@register_tool
def match_rigs_by_criteria(
    feature_name: Optional[str] = None,
    vehicle_program: Optional[str] = None,
    ecus_requested: Optional[list[str]] = None,
    rig_id: Optional[str] = None,
    platform: Optional[str] = None,
    domain: Optional[str] = None,
    ecu_config_pref: Optional[dict[str, str]] = None,
) -> dict:
    """Rank rigs by ECU topology and requested hardware configuration.

    Args:
        feature_name: Feature whose Real/CAN/Ethernet ECU requirements to match.
        vehicle_program: Target program; enables cross-program fallback ranking.
        ecus_requested: Raw ECU identifiers required on a rig.
        rig_id: Direct rig lookup, when not combined with a feature/ECU query.
        platform: Optional platform filter: dSPACE, Vector, or NI.
        domain: Optional rig domain filter.
        ecu_config_pref: Optional ECU-to-configuration requirements.
    Returns:
        Ranked rig metadata with match percentages, ECU breakdowns, upgrades,
        downgrades, missing ECUs, cross-program flags, and ECU split options.
    """
    result = CapabilityMatcherService(CSVHILRepository()).match_rigs(
        rig_id=rig_id,
        feature_name=feature_name,
        vehicle_program=vehicle_program,
        ecus_requested=ecus_requested,
        platform=platform,
        domain=domain,
        ecu_config_pref=ecu_config_pref,
    )
    st.session_state.matched_rigs = result.get("rigs", [])
    return result
