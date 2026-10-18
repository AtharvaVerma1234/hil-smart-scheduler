"""Deterministic rig capability matching and ranking."""

from itertools import combinations
from typing import Any, Optional

import pandas as pd

from src.config.constants import COMPATIBILITY_CUTOFF_PERCENT, FALLBACK_TOP_K_RIGS
from src.repositories.base import AbstractHILRepository
from src.utils.parsers import parse_pipe_list
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
        if platform:
            rigs = rigs[rigs["Rig_Platform"].str.casefold() == platform.casefold()]
        if domain:
            rigs = rigs[rigs["Rig_Domain"].str.casefold() == domain.casefold()]
        logger.debug("Rig filters applied: remaining_count=%d", len(rigs))

        if rig_id and not feature_name and not ecus_requested:
            selected = rigs[rigs["Rig_ID"].str.casefold() == rig_id.casefold()]
            results = [
                self._base_result(row, score=100.0, match_type="Direct Rig Request")
                for _, row in selected.iterrows()
            ]
            return self._result(self._apply_cutoff_and_sort(results))
        if feature_name:
            return self._result(
                self._match_by_feature(rigs, feature_name, vehicle_program)
            )
        if ecus_requested:
            results, combinations_found = self._match_by_ecus(
                rigs, ecus_requested, ecu_config_pref, vehicle_program
            )
            return self._result(
                self._apply_cutoff_and_sort(results),
                ecu_split_combinations=combinations_found,
            )
        if vehicle_program:
            results = []
            requested_program = vehicle_program.casefold()
            topology = self.repository.get_vehicle_program_ecus().fillna("")
            topology_row = topology[
                topology["Vehicle_Program"].str.casefold() == requested_program
            ]
            applicable = set(
                parse_pipe_list(topology_row.iloc[0]["Applicable_ECUs"])
            ) if not topology_row.empty else set()
            for _, row in rigs.iterrows():
                if str(row["Vehicle_Program"]).casefold() == requested_program:
                    results.append(
                        self._base_result(
                            row, 100.0, "Vehicle Program Match", is_cross_program=False
                        )
                    )
            cross_program_ecus = []
            for _, row in rigs.iterrows():
                if str(row["Vehicle_Program"]).casefold() == requested_program:
                    continue
                rig_ecus = self._rig_ecu_sets(row)
                rig_available = set().union(*rig_ecus.values())
                shared = sorted(applicable.intersection(rig_available))
                if shared:
                    cross_program_ecus.append(
                        {
                            "rig_id": row["Rig_ID"],
                            "vehicle_program": row["Vehicle_Program"],
                            "shared_ecus": shared,
                        }
                    )
            return self._result(
                sorted(results, key=lambda item: item["rig_id"]),
                cross_program_ecus=cross_program_ecus,
            )
        return self._result([])

    def _match_by_feature(
        self, rigs: pd.DataFrame, feature_name: str, vehicle_program: Optional[str]
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
                return []
            target_program = vehicle_program
            requirements_by_program = {
                program.casefold(): primary.iloc[0]
                for program in feature_rows["Vehicle_Program"].astype(str)
            }
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
        return self._apply_cutoff_and_sort(results)

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

        pairs = []
        for left, right in combinations(list(coverage_by_rig), 2):
            left_coverage = coverage_by_rig[left]
            right_coverage = coverage_by_rig[right]
            if set(left_coverage) | set(right_coverage) != set(requested):
                continue
            if set(left_coverage) == set(requested) or set(right_coverage) == set(requested):
                continue
            left_text = ", ".join(
                f"{ecu} ({config})" for ecu, config in left_coverage.items()
            )
            right_text = ", ".join(
                f"{ecu} ({config})"
                for ecu, config in right_coverage.items()
                if ecu not in left_coverage
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
    def _apply_cutoff_and_sort(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        nonzero = [result for result in results if result["match_score"] > 0.0]
        ordered = sorted(
            nonzero,
            key=lambda item: (item["is_cross_program"], -item["match_score"], item["rig_id"]),
        )
        above_cutoff = [
            result for result in ordered
            if result["match_score"] > COMPATIBILITY_CUTOFF_PERCENT
        ]
        return above_cutoff if len(above_cutoff) >= FALLBACK_TOP_K_RIGS else ordered[:FALLBACK_TOP_K_RIGS]

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
