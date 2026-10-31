"""Deterministic rig capability matching and ranking."""

from itertools import combinations
from typing import Any, Optional

import pandas as pd

from src.config.constants import (
    COMPATIBILITY_CUTOFF_PERCENT,
    TOP_RECOMMENDATIONS_PER_CATEGORY,
)
from src.repositories.base import AbstractHILRepository
from src.utils.parsers import natural_sort_key, parse_pipe_list, resolve_rig_id
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class CapabilityMatcherService:
    """Score rig capabilities against requested feature or ECU requirements."""

    def __init__(self, repository: AbstractHILRepository) -> None:
        self.repository = repository

    def match_rigs(
        self,
        rig_id: Optional[str] = None,
        feature_name: Optional[str] = None,
        vehicle_program: Optional[str] = None,
        ecus_requested: Optional[list[str]] = None,
        platform: Optional[str] = None,
        domain: Optional[str] = None,
        ecu_config_pref: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        logger.info(
            "Rig match started: rig_id=%s feature=%s vehicle_program=%s "
            "ecu_count=%d platform=%s domain=%s config_preferences=%d",
            rig_id,
            feature_name,
            vehicle_program,
            len(ecus_requested or []),
            platform,
            domain,
            len(ecu_config_pref or {}),
        )
        rigs = self.repository.get_all_rigs().fillna("")
        logger.debug("Loaded candidate rigs: count=%d", len(rigs))
        valid_rig_ids = {
            str(value).strip()
            for value in rigs["Rig_ID"].dropna()
            if str(value).strip()
        }
        resolved_rig_id = (
            resolve_rig_id(rig_id, valid_rig_ids) or rig_id if rig_id else None
        )
        if platform:
            rigs = rigs[
                rigs["Rig_Platform"].astype(str).str.casefold()
                == platform.casefold()
            ]
        if domain:
            rigs = rigs[
                rigs["Rig_Domain"].astype(str).str.casefold() == domain.casefold()
            ]
        logger.debug("Rig filters applied: remaining_count=%d", len(rigs))
        feature_program_exists = bool(
            feature_name
            and vehicle_program
            and self._feature_program_exists(feature_name, vehicle_program)
        )
        groups: dict[str, list[dict[str, Any]]] = {}
        split_combinations: list[dict[str, Any]] = []

        if feature_name:
            feature_target_program = (
                vehicle_program if feature_program_exists else None
            )
            feature_results = self._match_by_feature(
                rigs,
                feature_name,
                feature_target_program,
                allow_cross_program_fallback=bool(
                    feature_program_exists and not ecus_requested and not rig_id
                ),
            )
            feature_label = feature_name.upper()
            for result in feature_results:
                result["matched_for"] = feature_label
                if vehicle_program and not feature_program_exists:
                    result["is_cross_program"] = (
                        str(result.get("vehicle_program", "")).casefold()
                        != vehicle_program.casefold()
                    )
            if ecus_requested:
                for result in feature_results:
                    result["requested_ecu_breakdown"] = (
                        self._requested_ecu_breakdown(result, ecus_requested)
                    )
            groups[feature_label] = feature_results

        if ecus_requested:
            ecu_results, split_combinations = self._match_by_ecus(
                rigs, ecus_requested, ecu_config_pref, vehicle_program
            )
            ecu_label = ", ".join(ecus_requested).upper()
            ecu_results = self._apply_cutoff_and_sort(
                ecu_results,
                vehicle_program=vehicle_program,
                allow_cross_program_fallback=bool(
                    vehicle_program and not feature_name and not rig_id
                ),
            )
            for result in ecu_results:
                result["matched_for"] = ecu_label
            groups[ecu_label] = ecu_results

        separate_program_target = bool(vehicle_program)
        if vehicle_program and feature_name:
            separate_program_target = not feature_program_exists
        elif vehicle_program and ecus_requested:
            separate_program_target = not self._ecus_exist_in_program(
                ecus_requested,
                vehicle_program,
                rigs,
            )
        cross_program_ecus: list[dict[str, Any]] = []
        if separate_program_target and vehicle_program:
            program_results, cross_program_ecus = self._match_by_vehicle_program(
                rigs, vehicle_program
            )
            program_label = vehicle_program.upper()
            for result in program_results:
                result["matched_for"] = program_label
            groups[program_label] = program_results

        selected_rig = None
        direct_rig_is_separate = False
        if rig_id:
            selected = rigs[
                rigs["Rig_ID"].astype(str).str.casefold()
                == str(resolved_rig_id).casefold()
            ]
            if not selected.empty:
                row = selected.iloc[0]
                rig_key = str(row["Rig_ID"])
                if feature_name:
                    feature_target_program = (
                        vehicle_program if feature_program_exists else None
                    )
                    scored = self._match_by_feature(
                        selected, feature_name, feature_target_program
                    )
                    selected_rig = next(
                        (
                            result for result in scored
                            if str(result.get("rig_id", "")).casefold()
                            == rig_key.casefold()
                        ),
                        self._base_result(
                            row, 0.0, "Feature Match",
                            bool(
                                vehicle_program
                                and str(row["Vehicle_Program"]).casefold()
                                != vehicle_program.casefold()
                            ),
                        ),
                    )
                    feature_group = groups.setdefault(feature_name.upper(), [])
                    feature_matches_rig = any(
                        str(item.get("rig_id", "")).casefold() == rig_key.casefold()
                        for item in feature_group
                    )
                    if (
                        rig_id
                        and selected_rig.get("match_score", 0.0)
                        < COMPATIBILITY_CUTOFF_PERCENT
                    ):
                        direct_rig_is_separate = True
                        groups[feature_name.upper()] = [
                            item for item in feature_group
                            if str(item.get("rig_id", "")).casefold()
                            != rig_key.casefold()
                        ]
                    elif not feature_matches_rig:
                        selected_rig["matched_for"] = feature_name.upper()
                        if ecus_requested:
                            selected_rig["requested_ecu_breakdown"] = (
                                self._requested_ecu_breakdown(
                                    selected_rig, ecus_requested
                                )
                            )
                        feature_group.append(selected_rig)
                if ecus_requested:
                    scored, _ = self._match_by_ecus(
                        selected, ecus_requested, ecu_config_pref, vehicle_program
                    )
                    ecu_label = ", ".join(ecus_requested).upper()
                    ecu_group = groups.setdefault(ecu_label, [])
                    ecu_rig = scored[0] if scored else None
                    ecu_matches_rig = any(
                        str(item.get("rig_id", "")).casefold() == rig_key.casefold()
                        for item in ecu_group
                    )
                    if (
                        rig_id
                        and ecu_rig
                        and ecu_rig.get("match_score", 0.0)
                        < COMPATIBILITY_CUTOFF_PERCENT
                    ):
                        direct_rig_is_separate = True
                        groups[ecu_label] = [
                            item for item in ecu_group
                            if str(item.get("rig_id", "")).casefold()
                            != rig_key.casefold()
                        ]
                    elif ecu_rig and not ecu_matches_rig:
                        ecu_rig["matched_for"] = ecu_label
                        ecu_group.append(ecu_rig)
                    if selected_rig is None:
                        selected_rig = ecu_rig
                if selected_rig is None and not feature_name and not ecus_requested:
                    selected_rig = self._base_result(
                        row, 100.0, "Direct Rig Request"
                    )
                if selected_rig is not None and not (
                    feature_name or ecus_requested or vehicle_program
                ):
                    if not groups:
                        groups["DIRECT RIG REQUEST"] = [selected_rig]
                        selected_rig["matched_for"] = "DIRECT RIG REQUEST"
                    elif not any(
                        str(item.get("rig_id", "")).casefold() == rig_key.casefold()
                        for results in groups.values()
                        for item in results
                    ):
                        selected_rig["matched_for"] = "DIRECT RIG REQUEST"
                        groups["DIRECT RIG REQUEST"] = [selected_rig]
                if direct_rig_is_separate or not (
                    feature_name or ecus_requested
                ):
                    direct_label = str(resolved_rig_id).upper()
                    direct_result = self._base_result(
                        row, 100.0, "Direct Rig Request"
                    )
                    direct_result["matched_for"] = direct_label
                    if direct_rig_is_separate:
                        selected_rig = direct_result
                        for label, group_results in list(groups.items()):
                            groups[label] = [
                                item
                                for item in group_results
                                if str(item.get("rig_id", "")).casefold()
                                != rig_key.casefold()
                            ]
                    groups[direct_label] = [direct_result]
                    if direct_rig_is_separate:
                        selected_rig = direct_result

        results_by_id: dict[str, dict[str, Any]] = {}
        rig_group_membership: dict[str, set[str]] = {}
        for label, group_results in groups.items():
            for rank, item in enumerate(group_results):
                item_id = str(item.get("rig_id", item.get("Rig_ID", "")))
                if not item_id:
                    continue
                criterion_scores = item.setdefault("criterion_scores", {})
                criterion_scores[label] = float(item.get("match_score", 0.0))
                if (
                    rank < TOP_RECOMMENDATIONS_PER_CATEGORY
                    and item.get("match_score", 0.0) >= 100.0
                ):
                    rig_group_membership.setdefault(item_id, set()).add(label)
                existing = results_by_id.get(item_id)
                if existing is None:
                    results_by_id[item_id] = dict(item)
                else:
                    results_by_id[item_id] = self._merge_match_results(existing, item)

        expected_groups = set(groups)
        shared_rig_ids = sorted(
            rig_id_value
            for rig_id_value, labels in rig_group_membership.items()
            if len(expected_groups) > 1 and labels >= expected_groups
        )
        for item_id, item in results_by_id.items():
            labels = sorted(rig_group_membership.get(item_id, set()))
            item["matched_request_labels"] = labels
            item["shared_across_requests"] = item_id in shared_rig_ids
            if labels:
                item["matched_for"] = " + ".join(labels)
            elif item.get("criterion_scores"):
                best_label = max(
                    item["criterion_scores"],
                    key=item["criterion_scores"].get,
                )
                item["matched_for"] = best_label

        final_results = self._sort_results(list(results_by_id.values()))
        if selected_rig is not None and not any(
            str(item.get("rig_id", item.get("Rig_ID", ""))).casefold()
            == str(selected_rig.get("rig_id", "")).casefold()
            for item in final_results
        ):
            final_results.append(selected_rig)
        result_extras: dict[str, Any] = {
            "shared_across_requests": shared_rig_ids,
            "request_groups": {
                label: [
                    str(item.get("rig_id", item.get("Rig_ID", "")))
                    for item in group_results
                ]
                for label, group_results in groups.items()
            },
        }
        if ecus_requested:
            result_extras["ecu_split_combinations"] = split_combinations
        if cross_program_ecus:
            result_extras["cross_program_ecus"] = cross_program_ecus
        return self._result(final_results, **result_extras)

    def _feature_program_exists(self, feature_name: str, vehicle_program: str) -> bool:
        requirements = self.repository.get_feature_requirements().fillna("")
        return not requirements[
            requirements["Feature_Name"].astype(str).str.casefold()
            .eq(feature_name.casefold())
            & requirements["Vehicle_Program"].astype(str).str.casefold()
            .eq(vehicle_program.casefold())
        ].empty

    def _ecus_exist_in_program(
        self,
        ecus_requested: list[str],
        vehicle_program: str,
        rigs: pd.DataFrame,
    ) -> bool:
        requested = {
            ecu.strip().casefold() for ecu in ecus_requested if ecu.strip()
        }
        if not requested:
            return False

        topology = self.repository.get_vehicle_program_ecus().fillna("")
        program_rows = topology[
            topology["Vehicle_Program"].astype(str).str.casefold()
            == vehicle_program.casefold()
        ]
        if not program_rows.empty:
            applicable = {
                ecu.casefold()
                for ecu in parse_pipe_list(program_rows.iloc[0]["Applicable_ECUs"])
            }
            if requested.intersection(applicable):
                return True

        program_rigs = rigs[
            rigs["Vehicle_Program"].astype(str).str.casefold()
            == vehicle_program.casefold()
        ]
        for _, rig in program_rigs.iterrows():
            available = {
                ecu.casefold()
                for ecu_set in self._rig_ecu_sets(rig).values()
                for ecu in ecu_set
            }
            if requested.intersection(available):
                return True
        return False

    def _match_by_vehicle_program(
        self, rigs: pd.DataFrame, vehicle_program: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        requested_program = vehicle_program.casefold()
        topology = self.repository.get_vehicle_program_ecus().fillna("")
        topology_row = topology[
            topology["Vehicle_Program"].astype(str).str.casefold()
            == requested_program
        ]
        applicable = (
            set(parse_pipe_list(topology_row.iloc[0]["Applicable_ECUs"]))
            if not topology_row.empty
            else set()
        )
        results = [
            self._base_result(row, 100.0, "Vehicle Program Match")
            for _, row in rigs.iterrows()
            if str(row["Vehicle_Program"]).casefold() == requested_program
        ]
        cross_program_ecus = []
        for _, row in rigs.iterrows():
            if str(row["Vehicle_Program"]).casefold() == requested_program:
                continue
            rig_available = set().union(*self._rig_ecu_sets(row).values())
            shared = sorted(applicable.intersection(rig_available))
            if shared:
                cross_program_ecus.append(
                    {
                        "rig_id": row["Rig_ID"],
                        "vehicle_program": row["Vehicle_Program"],
                        "shared_ecus": shared,
                    }
                )
        return self._apply_cutoff_and_sort(results), cross_program_ecus

    def _requested_ecu_breakdown(
        self, rig: dict[str, Any], ecus_requested: list[str]
    ) -> list[dict[str, str]]:
        available_sets = {
            "Real": set(rig.get("real_ecus", [])),
            "CAN_Sim": set(rig.get("can_sim_ecus", [])),
            "Eth_Sim": set(rig.get("eth_sim_ecus", [])),
        }
        return [
            {
                "ecu": ecu.upper(),
                "available": next(
                    (
                        configuration
                        for configuration in ("Real", "CAN_Sim", "Eth_Sim")
                        if ecu.upper() in available_sets[configuration]
                    ),
                    "Missing",
                ),
            }
            for ecu in ecus_requested
        ]

    @staticmethod
    def _merge_match_results(
        existing: dict[str, Any], incoming: dict[str, Any]
    ) -> dict[str, Any]:
        preferred = (
            incoming
            if incoming.get("match_score", 0) > existing.get("match_score", 0)
            else existing
        )
        merged = dict(preferred)
        for key in (
            "smart_upgrades",
            "downgrades",
            "missing",
            "ecu_breakdown",
            "requested_ecu_breakdown",
        ):
            values = []
            for item in (*existing.get(key, []), *incoming.get(key, [])):
                if item not in values:
                    values.append(item)
            if values:
                merged[key] = values
        labels = list(
            dict.fromkeys(
                [
                    *str(existing.get("matched_for", "")).split(" + "),
                    *str(incoming.get("matched_for", "")).split(" + "),
                ]
            )
        )
        merged["matched_for"] = " + ".join(label for label in labels if label)
        merged_criterion_scores = dict(existing.get("criterion_scores", {}))
        for label, score in incoming.get("criterion_scores", {}).items():
            merged_criterion_scores[label] = max(
                merged_criterion_scores.get(label, 0.0), score
            )
        if merged_criterion_scores:
            merged["criterion_scores"] = merged_criterion_scores
        return merged

    def _match_by_feature(
        self,
        rigs: pd.DataFrame,
        feature_name: str,
        vehicle_program: Optional[str],
        allow_cross_program_fallback: bool = False,
    ) -> list[dict[str, Any]]:
        requirements = self.repository.get_feature_requirements().fillna("")
        feature_rows = requirements[
            requirements["Feature_Name"].str.casefold() == feature_name.casefold()
        ]
        if feature_rows.empty:
            logger.warning(
                "No feature requirements found: feature=%s vehicle_program=%s",
                feature_name,
                vehicle_program,
            )
            return []
        if vehicle_program:
            primary = feature_rows[
                feature_rows["Vehicle_Program"].str.casefold()
                == vehicle_program.casefold()
            ]
            if primary.empty:
                fallback_requirement = feature_rows.iloc[0]
                requirements_by_program = {
                    str(program).casefold(): fallback_requirement
                    for program in feature_rows["Vehicle_Program"].astype(str)
                }
            else:
                requirements_by_program = {
                    program.casefold(): primary.iloc[0]
                    for program in feature_rows["Vehicle_Program"].astype(str)
                }
            target_program = vehicle_program
        else:
            target_program = str(feature_rows.iloc[0]["Vehicle_Program"])
            requirements_by_program = {
                str(row["Vehicle_Program"]).casefold(): row
                for _, row in feature_rows.iterrows()
            }

        results = []
        for _, rig in rigs.iterrows():
            requirement = requirements_by_program.get(
                str(rig["Vehicle_Program"]).casefold(), feature_rows.iloc[0]
            )
            req_real = set(parse_pipe_list(requirement["Real_ECUs_Required"]))
            req_can = set(parse_pipe_list(requirement["CAN_Sim_Needed"]))
            req_eth = set(parse_pipe_list(requirement["Eth_Sim_Needed"]))
            total = len(req_real) + len(req_can) + len(req_eth)
            rig_sets = self._rig_ecu_sets(rig)
            earned = 0.0
            smart_upgrades: list[str] = []
            downgrades: list[str] = []
            missing: list[str] = []
            breakdown: list[dict[str, str]] = []
            for ecu in sorted(req_real):
                if ecu in rig_sets["Real"]:
                    earned += 1.0
                    breakdown.append({"ecu": ecu, "required": "Real", "available": "Real"})
                elif ecu in rig_sets["CAN_Sim"] or ecu in rig_sets["Eth_Sim"]:
                    earned += 0.5
                    sim_label = "CAN Sim" if ecu in rig_sets["CAN_Sim"] else "Eth Sim"
                    downgrades.append(f"{ecu} (Real required, only {sim_label} available)")
                    breakdown.append({"ecu": ecu, "required": "Real", "available": sim_label})
                else:
                    missing.append(f"{ecu} (Real missing)")
                    breakdown.append({"ecu": ecu, "required": "Real", "available": "Missing"})
            for ecu, required, available_key, sim_label in (
                (ecu, "CAN_Sim", "CAN_Sim", "CAN simulation")
                for ecu in sorted(req_can)
            ):
                if ecu in rig_sets[available_key]:
                    earned += 1.0
                    breakdown.append({"ecu": ecu, "required": required, "available": sim_label})
                elif ecu in rig_sets["Real"]:
                    earned += 1.0
                    smart_upgrades.append(
                        f"{ecu} CAN simulation missing, but Real {ecu} variant is physically connected"
                    )
                    breakdown.append({"ecu": ecu, "required": required, "available": "Real (upgrade)"})
                else:
                    missing.append(f"{ecu} (CAN Sim missing)")
                    breakdown.append({"ecu": ecu, "required": required, "available": "Missing"})
            for ecu in sorted(req_eth):
                if ecu in rig_sets["Eth_Sim"]:
                    earned += 1.0
                    breakdown.append({"ecu": ecu, "required": "Eth_Sim", "available": "Eth Sim"})
                elif ecu in rig_sets["Real"]:
                    earned += 1.0
                    smart_upgrades.append(
                        f"{ecu} Eth simulation missing, but Real {ecu} variant is physically connected"
                    )
                    breakdown.append({"ecu": ecu, "required": "Eth_Sim", "available": "Real (upgrade)"})
                else:
                    missing.append(f"{ecu} (Eth Sim missing)")
                    breakdown.append({"ecu": ecu, "required": "Eth_Sim", "available": "Missing"})
            is_cross = bool(
                vehicle_program
                and str(rig["Vehicle_Program"]).casefold() != target_program.casefold()
            )
            result = self._base_result(
                rig,
                round(earned / total * 100.0, 1) if total else 100.0,
                "Feature Match",
                is_cross,
            )
            result.update(
                {
                    "smart_upgrades": smart_upgrades,
                    "downgrades": downgrades,
                    "missing": missing,
                    "ecu_breakdown": breakdown,
                }
            )
            results.append(result)
        return self._apply_cutoff_and_sort(
            results,
            vehicle_program=vehicle_program,
            allow_cross_program_fallback=allow_cross_program_fallback,
        )

    def _match_by_ecus(
        self,
        rigs: pd.DataFrame,
        ecus_requested: list[str],
        ecu_config_pref: Optional[dict[str, str]],
        vehicle_program: Optional[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        requested = list(dict.fromkeys(item.strip().upper() for item in ecus_requested if item.strip()))
        preferences = {
            key.strip().upper(): value.strip().replace(" ", "_").upper()
            for key, value in (ecu_config_pref or {}).items()
        }
        results = []
        coverage_by_rig: dict[str, dict[str, str]] = {}
        for _, rig in rigs.iterrows():
            sets = self._rig_ecu_sets(rig)
            earned = 0.0
            breakdown = []
            smart_upgrades = []
            downgrades = []
            missing = []
            coverage: dict[str, str] = {}
            for ecu in requested:
                configurations = [
                    (config, label)
                    for config, label in (
                        ("Real", "Real"),
                        ("CAN_Sim", "CAN_Sim"),
                        ("Eth_Sim", "Eth_Sim"),
                    )
                    if ecu in sets[config]
                ]
                preferred = preferences.get(ecu)
                actual = next((config for config, _ in configurations if config == preferred), None)
                if not preferred:
                    if configurations:
                        actual = configurations[0][0]
                        earned += 1.0
                        coverage[ecu] = actual
                    else:
                        missing.append(f"{ecu} (missing)")
                elif actual:
                    earned += 1.0
                    coverage[ecu] = actual
                elif configurations and preferred in ("CAN_SIM", "ETH_SIM") and "Real" in sets and ecu in sets["Real"]:
                    earned += 1.0
                    actual = "Real"
                    coverage[ecu] = actual
                    smart_upgrades.append(
                        f"{ecu} {preferred.replace('_', ' ')} requested, but Real {ecu} is physically connected"
                    )
                elif configurations and preferred == "REAL":
                    actual = configurations[0][0]
                    earned += 0.5
                    coverage[ecu] = actual
                    downgrades.append(
                        f"{ecu} (Real requested, only {actual.replace('_', ' ')} available)"
                    )
                elif configurations:
                    actual = configurations[0][0]
                    missing.append(f"{ecu} ({preferred} configuration unavailable)")
                else:
                    missing.append(f"{ecu} (missing)")
                breakdown.append(
                    {
                        "ecu": ecu,
                        "required": preferred or "Any",
                        "available": actual or "Missing",
                    }
                )
            is_cross = bool(
                vehicle_program
                and str(rig["Vehicle_Program"]).casefold() != vehicle_program.casefold()
            )
            result = self._base_result(
                rig,
                round(earned / len(requested) * 100.0, 1) if requested else 0.0,
                "ECU Match",
                is_cross,
            )
            result.update(
                {
                    "ecu_breakdown": breakdown,
                    "configurations": [
                        f"{entry['ecu']} ({entry['available']})"
                        for entry in breakdown
                        if entry["available"] != "Missing"
                    ],
                    "smart_upgrades": smart_upgrades,
                    "downgrades": downgrades,
                    "missing": missing,
                }
            )
            results.append(result)
            coverage_by_rig[str(rig["Rig_ID"])] = coverage

        candidate_rigs = self._apply_cutoff_and_sort(results)
        pairs = []
        for left_result, right_result in combinations(candidate_rigs, 2):
            left = str(left_result["rig_id"])
            right = str(right_result["rig_id"])
            left_coverage = coverage_by_rig[left]
            right_coverage = coverage_by_rig[right]
            left_assignment: dict[str, str] = {}
            right_assignment: dict[str, str] = {}
            for ecu in requested:
                left_config = left_coverage.get(ecu)
                right_config = right_coverage.get(ecu)
                if left_config and right_config:
                    if left_config == "Real" and right_config != "Real":
                        left_assignment[ecu] = left_config
                    elif right_config == "Real" and left_config != "Real":
                        right_assignment[ecu] = right_config
                    else:
                        left_assignment[ecu] = left_config
                elif left_config:
                    left_assignment[ecu] = left_config
                elif right_config:
                    right_assignment[ecu] = right_config
            if not left_assignment or not right_assignment:
                continue
            left_text = ", ".join(
                f"{ecu} ({config})" for ecu, config in left_assignment.items()
            )
            right_text = ", ".join(
                f"{ecu} ({config})"
                for ecu, config in right_assignment.items()
            )
            pairs.append(
                {
                    "rig_ids": [left, right],
                    "description": f"{left_text} on {left} AND {right_text} on {right}",
                }
            )
        return results, pairs

    def _rig_ecu_sets(self, rig: pd.Series) -> dict[str, set[str]]:
        return {
            "Real": set(parse_pipe_list(rig.get("Real_Connected_Components"))),
            "CAN_Sim": set(parse_pipe_list(rig.get("CAN_Sim_ECUs"))),
            "Eth_Sim": set(parse_pipe_list(rig.get("Eth_Sim_ECUs"))),
        }

    def _base_result(
        self,
        row: pd.Series,
        score: float,
        match_type: str,
        is_cross_program: bool = False,
    ) -> dict[str, Any]:
        return {
            **row.to_dict(),
            "rig_id": row.get("Rig_ID", ""),
            "vehicle_program": row.get("Vehicle_Program", ""),
            "platform": row.get("Rig_Platform", ""),
            "domain": row.get("Rig_Domain", ""),
            "rig_engineer": row.get("Rig_Engineer", ""),
            "real_ecus": parse_pipe_list(row.get("Real_Connected_Components")),
            "can_sim_ecus": parse_pipe_list(row.get("CAN_Sim_ECUs")),
            "eth_sim_ecus": parse_pipe_list(row.get("Eth_Sim_ECUs")),
            "match_score": score,
            "match_type": match_type,
            "is_cross_program": is_cross_program,
            "smart_upgrades": [],
            "downgrades": [],
            "missing": [],
            "ecu_breakdown": [],
        }

    @staticmethod
    def _sort_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        nonzero = [result for result in results if result["match_score"] > 0.0]
        return sorted(
            nonzero,
            key=lambda item: (
                item["is_cross_program"],
                -item["match_score"],
                -sum(
                    1
                    for breakdown in item.get("ecu_breakdown", [])
                    if str(breakdown.get("available", "")) == "Real"
                ),
                tuple(
                    (0, token) if isinstance(token, str) else (1, token)
                    for token in natural_sort_key(item.get("rig_id", ""))
                ),
            ),
        )

    @classmethod
    def _apply_cutoff_and_sort(
        cls,
        results: list[dict[str, Any]],
        vehicle_program: Optional[str] = None,
        allow_cross_program_fallback: bool = False,
    ) -> list[dict[str, Any]]:
        ordered = cls._sort_results(results)
        above_cutoff = [
            result for result in ordered
            if result["match_score"] > COMPATIBILITY_CUTOFF_PERCENT
        ]
        selected = above_cutoff[:TOP_RECOMMENDATIONS_PER_CATEGORY]
        if len(selected) < TOP_RECOMMENDATIONS_PER_CATEGORY:
            selected_ids = {id(result) for result in selected}
            selected.extend(
                result
                for result in ordered
                if id(result) not in selected_ids
            )
            selected = selected[:TOP_RECOMMENDATIONS_PER_CATEGORY]

        if (
            allow_cross_program_fallback
            and vehicle_program
            and len(selected) == TOP_RECOMMENDATIONS_PER_CATEGORY
            and all(not result.get("is_cross_program", False) for result in selected)
        ):
            cross_program = next(
                (
                    result for result in ordered
                    if result.get("is_cross_program", False)
                    and result["match_score"] >= COMPATIBILITY_CUTOFF_PERCENT
                ),
                None,
            )
            if cross_program is not None:
                selected.append(cross_program)
        return selected

    @staticmethod
    def _result(rigs: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        logger.info(
            "Rig match completed: result_count=%d top_matches=%s",
            len(rigs),
            [
                {
                    "rig_id": item.get("rig_id"),
                    "score": item.get("match_score"),
                    "cross_program": item.get("is_cross_program"),
                }
                for item in rigs[:4]
            ],
        )
        return {"rigs": rigs, "ranked_rigs": rigs, **extra}
