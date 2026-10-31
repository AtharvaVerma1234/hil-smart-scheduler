"""Phase 1 topology inspection and deterministic rig matching tools."""

import re
from typing import Optional

import streamlit as st

from src.agent.tools.registry import register_tool
from src.config.constants import TOP_RECOMMENDATIONS_PER_CATEGORY
from src.repositories import get_repository
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
    repository = get_repository()
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
    result = CapabilityMatcherService(get_repository()).match_rigs(
        rig_id=rig_id,
        feature_name=feature_name,
        vehicle_program=vehicle_program,
        ecus_requested=ecus_requested,
        platform=platform,
        domain=domain,
        ecu_config_pref=ecu_config_pref,
    )
    label_parts = [
        str(part).upper()
        for part in (
            feature_name,
            vehicle_program,
            ", ".join(ecus_requested) if ecus_requested else None,
            rig_id,
            platform,
            domain,
        )
        if part
    ]
    target_label = " + ".join(label_parts) or "QUERY"
    original_rigs = result.get("rigs", [])
    rigs_by_result_id = {
        str(rig.get("rig_id", rig.get("Rig_ID", ""))): rig
        for rig in original_rigs
    }
    request_groups = result.get("request_groups", {})
    current_ids: set[str] = set()
    top_targets_by_id: dict[str, set[str]] = {}
    if request_groups:
        for target, group_ids in request_groups.items():
            top_ids = group_ids[:TOP_RECOMMENDATIONS_PER_CATEGORY]
            current_ids.update(top_ids)
            for rig_id_value in top_ids:
                top_targets_by_id.setdefault(str(rig_id_value), set()).add(target)
            if len(group_ids) > TOP_RECOMMENDATIONS_PER_CATEGORY:
                fallback_id = str(group_ids[TOP_RECOMMENDATIONS_PER_CATEGORY])
                fallback = rigs_by_result_id.get(fallback_id)
                fallback_score = (
                    fallback.get("criterion_scores", {}).get(
                        target,
                        fallback.get("match_score", 0.0),
                    )
                    if fallback
                    else 0.0
                )
                if (
                    fallback
                    and fallback.get("is_cross_program", False)
                    and fallback_score >= 50.0
                ):
                    current_ids.add(fallback_id)
    else:
        current_ids.update(
            str(rig.get("rig_id", rig.get("Rig_ID", "")))
            for rig in original_rigs[:TOP_RECOMMENDATIONS_PER_CATEGORY]
        )
        for rig_id_value in current_ids:
            top_targets_by_id.setdefault(rig_id_value, set()).add(target_label)

    current_rigs = [
        dict(rig)
        for rig in original_rigs
        if str(rig.get("rig_id", rig.get("Rig_ID", ""))) in current_ids
    ]
    for rig in current_rigs:
        rig["matched_for"] = rig.get("matched_for") or target_label
        criterion_scores = rig.get("criterion_scores") or {
            rig["matched_for"]: float(rig.get("match_score", 0.0))
        }
        rig["scores_by_target"] = {
            str(label): float(score)
            for label, score in criterion_scores.items()
        }
        rig["top3_targets"] = sorted(
            top_targets_by_id.get(
                str(rig.get("rig_id", rig.get("Rig_ID", ""))),
                set(),
            )
        )
    result["rigs"] = current_rigs
    result["ranked_rigs"] = current_rigs
    st.session_state["_turn_last_batch_rig_ids"] = [
        str(rig.get("rig_id", rig.get("Rig_ID", "")))
        for rig in current_rigs
        if rig.get("rig_id") or rig.get("Rig_ID")
    ]

    current_targets = list(request_groups) if request_groups else (
        [target_label] if target_label != "QUERY" else []
    )
    match_targets = st.session_state.setdefault("_turn_match_targets", [])
    for target in current_targets:
        if target not in match_targets:
            match_targets.append(target)
    if rig_id:
        direct_rig_ids = st.session_state.setdefault("_turn_direct_rig_ids", [])
        normalized_direct_id = str(rig_id).strip().upper()
        if normalized_direct_id not in direct_rig_ids:
            direct_rig_ids.append(normalized_direct_id)

    rigs_by_id = st.session_state.setdefault("_turn_matched_rigs_by_id", {})
    for rig in current_rigs:
        rig_id_value = str(rig.get("rig_id", rig.get("Rig_ID", "")))
        existing = rigs_by_id.get(rig_id_value)
        existing = dict(existing) if existing else {}
        preferred = (
            rig
            if not existing
            or rig.get("match_score", 0) > existing.get("match_score", 0)
            else existing
        )
        merged = {
            **preferred,
        }
        scores_by_target = dict(existing.get("scores_by_target", {}))
        scores_by_target.update(rig.get("scores_by_target", {}))
        top3_targets = set(existing.get("top3_targets", []))
        top3_targets.update(rig.get("top3_targets", []))
        if scores_by_target:
            merged["scores_by_target"] = scores_by_target
        merged["top3_targets"] = sorted(top3_targets)
        for key in (
            "smart_upgrades",
            "downgrades",
            "missing",
            "ecu_breakdown",
            "requested_ecu_breakdown",
            "matched_request_labels",
        ):
            values = []
            for item in (*existing.get(key, []), *rig.get(key, [])):
                if item not in values:
                    values.append(item)
            if values:
                merged[key] = values
        shared_targets = [
            target
            for target in match_targets
            if target in top3_targets and scores_by_target.get(target, 0.0) == 100.0
        ]
        merged["shared_across_requests"] = (
            len(match_targets) > 1 and len(shared_targets) == len(match_targets)
        )
        if merged["shared_across_requests"]:
            merged["matched_for"] = " & ".join(shared_targets)
        else:
            merged["matched_for"] = (
                rig.get("matched_for")
                if rig.get("match_score", 0) >= existing.get("match_score", 0)
                else existing.get("matched_for", rig.get("matched_for", ""))
            )
        rigs_by_id[rig_id_value] = merged

    st.session_state["matched_rigs"] = list(rigs_by_id.values())
    turn_targets = match_targets
    shared_rig_ids = [
        rig_id_value
        for rig_id_value, rig in rigs_by_id.items()
        if len(turn_targets) > 1
        and all(
            target in rig.get("top3_targets", [])
            and rig.get("scores_by_target", {}).get(target, 0.0) == 100.0
            for target in turn_targets
        )
    ]
    for rig in current_rigs:
        accumulated = rigs_by_id.get(
            str(rig.get("rig_id", rig.get("Rig_ID", ""))), {}
        )
        rig["shared_across_requests"] = accumulated.get(
            "shared_across_requests", False
        )
        rig["scores_by_target"] = accumulated.get(
            "scores_by_target", rig.get("scores_by_target", {})
        )
        if rig["shared_across_requests"]:
            rig["matched_for"] = accumulated.get("matched_for", rig["matched_for"])
    result["shared_across_requests"] = shared_rig_ids
    result.pop("ranked_rigs", None)
    if "cross_program_ecus" in result:
        if all(not rig.get("is_cross_program", False) for rig in current_rigs):
            result.pop("cross_program_ecus", None)
        else:
            result["cross_program_ecus"] = result["cross_program_ecus"][:3]
    raw_csv_fields = {
        "Real_Connected_Components",
        "CAN_Sim_ECUs",
        "Eth_Sim_ECUs",
        "Rig_ID",
        "Vehicle_Program",
        "Rig_Domain",
        "Rig_Platform",
        "Rig_Engineer",
    }
    for rig in current_rigs:
        for field in raw_csv_fields:
            rig.pop(field, None)
        if feature_name and not ecus_requested:
            rig["ecu_breakdown"] = [
                item
                for item in rig.get("ecu_breakdown", [])
                if _ecu_breakdown_is_discrepant(item)
            ]
    return result


def _ecu_breakdown_is_discrepant(item: dict) -> bool:
    def _norm(value: object) -> str:
        text = str(value).casefold().replace("simulation", "sim")
        return re.sub(r"[\s_()]", "", text)

    return _norm(item.get("required", "")) != _norm(item.get("available", ""))
