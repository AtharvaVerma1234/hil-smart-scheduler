"""Regression tests for rig ranking, ECU splits, and availability totals."""

import unittest
from unittest.mock import Mock

import pandas as pd

from src.services.capability_matcher import CapabilityMatcherService
from src.services.slot_scheduler import SlotSchedulerService


def _rig(
    rig_id: str,
    real: str = "",
    can_sim: str = "",
    eth_sim: str = "",
    vehicle_program: str = "VEHICLE_PROGRAM_1",
) -> dict[str, str]:
    return {
        "Rig_ID": rig_id,
        "Vehicle_Program": vehicle_program,
        "Rig_Platform": "NI",
        "Rig_Domain": "DOMAIN_1",
        "Rig_Engineer": "ENG_1",
        "Real_Connected_Components": real,
        "CAN_Sim_ECUs": can_sim,
        "Eth_Sim_ECUs": eth_sim,
    }


class CapabilityMatcherRegressionTests(unittest.TestCase):
    def test_unsupported_feature_program_pair_returns_both_target_groups(self) -> None:
        repository = Mock()
        repository.get_feature_requirements.return_value = pd.DataFrame(
            [
                {
                    "Feature_Name": "FEATURE_1",
                    "Vehicle_Program": "VEHICLE_PROGRAM_1",
                    "Real_ECUs_Required": "ECU1",
                    "CAN_Sim_Needed": "",
                    "Eth_Sim_Needed": "",
                }
            ]
        )
        repository.get_vehicle_program_ecus.return_value = pd.DataFrame(
            [
                {
                    "Vehicle_Program": "VEHICLE_PROGRAM_6",
                    "Applicable_ECUs": "ECU1",
                }
            ]
        )
        repository.get_all_rigs.return_value = pd.DataFrame(
            [
                _rig("RIG_1", real="ECU1", vehicle_program="VEHICLE_PROGRAM_1"),
                _rig("RIG_6", real="ECU1", vehicle_program="VEHICLE_PROGRAM_6"),
            ]
        )

        result = CapabilityMatcherService(repository).match_rigs(
            feature_name="FEATURE_1",
            vehicle_program="VEHICLE_PROGRAM_6",
        )

        self.assertEqual(
            result["request_groups"],
            {
                "FEATURE_1": ["RIG_1", "RIG_6"],
                "VEHICLE_PROGRAM_6": ["RIG_6"],
            },
        )
        self.assertEqual(result["shared_across_requests"], ["RIG_6"])
        rig_six = next(rig for rig in result["rigs"] if rig["rig_id"] == "RIG_6")
        self.assertEqual(rig_six["match_score"], 100.0)
        self.assertEqual(rig_six["matched_request_labels"], [
            "FEATURE_1",
            "VEHICLE_PROGRAM_6",
        ])

    def test_feature_ecu_platform_criteria_merge_and_report_shared_rigs(self) -> None:
        repository = Mock()
        repository.get_feature_requirements.return_value = pd.DataFrame(
            [
                {
                    "Feature_Name": "FEATURE_1",
                    "Vehicle_Program": "VEHICLE_PROGRAM_1",
                    "Real_ECUs_Required": "ECU1",
                    "CAN_Sim_Needed": "",
                    "Eth_Sim_Needed": "",
                }
            ]
        )
        repository.get_all_rigs.return_value = pd.DataFrame(
            [
                {
                    **_rig("RIG_1", real="ECU1|ECU2"),
                    "Rig_Platform": "Vector",
                },
                {
                    **_rig("RIG_2", real="ECU2"),
                    "Rig_Platform": "Vector",
                },
                _rig("RIG_3", real="ECU1"),
            ]
        )

        result = CapabilityMatcherService(repository).match_rigs(
            feature_name="FEATURE_1",
            ecus_requested=["ECU1", "ECU2"],
            platform="Vector",
        )

        self.assertEqual(result["shared_across_requests"], ["RIG_1"])
        self.assertEqual(
            result["request_groups"],
            {
                "FEATURE_1": ["RIG_1"],
                "ECU1, ECU2": ["RIG_1", "RIG_2"],
            },
        )
        self.assertEqual(
            [rig["rig_id"] for rig in result["rigs"]],
            ["RIG_1", "RIG_2"],
        )
        rig_one = result["rigs"][0]
        self.assertTrue(rig_one["shared_across_requests"])
        self.assertEqual(
            rig_one["requested_ecu_breakdown"],
            [
                {"ecu": "ECU1", "available": "Real"},
                {"ecu": "ECU2", "available": "Real"},
            ],
        )

    def test_direct_rig_is_a_full_match_when_combined_with_feature(self) -> None:
        repository = Mock()
        repository.get_feature_requirements.return_value = pd.DataFrame(
            [
                {
                    "Feature_Name": "FEATURE_1",
                    "Vehicle_Program": "VEHICLE_PROGRAM_1",
                    "Real_ECUs_Required": (
                        "ECU1|ECU2|ECU3|ECU4|ECU5|ECU6|ECU7|ECU8|"
                        "ECU9|ECU10|ECU11|ECU12"
                    ),
                    "CAN_Sim_Needed": "",
                    "Eth_Sim_Needed": "",
                }
            ]
        )
        repository.get_all_rigs.return_value = pd.DataFrame(
            [
                _rig("RIG_1", real="ECU1"),
                _rig(
                    "RIG_10",
                    real="ECU12",
                    vehicle_program="VEHICLE_PROGRAM_4",
                ),
            ]
        )

        result = CapabilityMatcherService(repository).match_rigs(
            rig_id="RIG_10",
            feature_name="FEATURE_1",
            vehicle_program="VEHICLE_PROGRAM_1",
        )

        direct_rig = next(rig for rig in result["rigs"] if rig["rig_id"] == "RIG_10")
        self.assertEqual(direct_rig["match_score"], 100.0)
        self.assertEqual(direct_rig["matched_for"], "RIG_10")
        self.assertEqual(direct_rig["missing"], [])
        self.assertEqual(direct_rig["ecu_breakdown"], [])
        self.assertIn("RIG_10", result["request_groups"])
        self.assertNotIn("RIG_10", result["request_groups"]["FEATURE_1"])

    def test_fewer_than_three_above_cutoff_returns_top_three_overall(self) -> None:
        results = [
            {
                "rig_id": f"RIG_{number}",
                "is_cross_program": False,
                "match_score": 100.0 if number < 4 else 25.0,
                "ecu_breakdown": [],
            }
            for number in range(1, 6)
        ]

        ordered = CapabilityMatcherService._apply_cutoff_and_sort(results)

        self.assertEqual(
            [(item["rig_id"], item["match_score"]) for item in ordered],
            [
                ("RIG_1", 100.0),
                ("RIG_2", 100.0),
                ("RIG_3", 100.0),
            ],
        )

    def test_numeric_rig_id_sort_real_ecu_tie_break_and_top_three(self) -> None:
        rigs = [
            {
                "rig_id": f"RIG_{number}",
                "is_cross_program": False,
                "match_score": 75.0,
                "ecu_breakdown": [{"available": "Real"}] * (2 if number == 19 else 1),
            }
            for number in (19, 4, *range(1, 12))
        ]

        ordered = CapabilityMatcherService._apply_cutoff_and_sort(rigs)

        self.assertEqual(len(ordered), 3)
        self.assertEqual(
            [item["rig_id"] for item in ordered[:3]],
            ["RIG_19", "RIG_1", "RIG_2"],
        )
        self.assertNotIn("RIG_11", [item["rig_id"] for item in ordered])

        tied = [
            {
                "rig_id": "RIG_19",
                "is_cross_program": False,
                "match_score": 75.0,
                "ecu_breakdown": [{"available": "Real"}],
            },
            {
                "rig_id": "RIG_4",
                "is_cross_program": False,
                "match_score": 75.0,
                "ecu_breakdown": [{"available": "Real"}],
            },
        ]
        self.assertEqual(
            [item["rig_id"] for item in CapabilityMatcherService._apply_cutoff_and_sort(tied)],
            ["RIG_4", "RIG_19"],
        )

    def test_explicit_program_adds_one_cross_program_fallback(self) -> None:
        repository = Mock()
        repository.get_feature_requirements.return_value = pd.DataFrame(
            [
                {
                    "Feature_Name": "FEATURE_1",
                    "Vehicle_Program": "VEHICLE_PROGRAM_1",
                    "Real_ECUs_Required": "ECU1",
                    "CAN_Sim_Needed": "ECU2",
                    "Eth_Sim_Needed": "",
                }
            ]
        )
        repository.get_all_rigs.return_value = pd.DataFrame(
            [
                _rig(f"RIG_{number}", real="ECU1", can_sim="ECU2")
                for number in (1, 2, 3)
            ]
            + [
                _rig(
                    "RIG_4",
                    real="ECU1",
                    vehicle_program="VEHICLE_PROGRAM_2",
                )
            ]
        )

        result = CapabilityMatcherService(repository).match_rigs(
            feature_name="FEATURE_1",
            vehicle_program="VEHICLE_PROGRAM_1",
        )["rigs"]

        self.assertEqual([rig["rig_id"] for rig in result], [
            "RIG_1",
            "RIG_2",
            "RIG_3",
            "RIG_4",
        ])
        self.assertEqual(result[-1]["match_score"], 50.0)
        self.assertTrue(result[-1]["is_cross_program"])

    def test_feature_template_falls_back_for_unlisted_vehicle_program(self) -> None:
        repository = Mock()
        repository.get_feature_requirements.return_value = pd.DataFrame(
            [
                {
                    "Feature_Name": "FEATURE_5",
                    "Vehicle_Program": "VEHICLE_PROGRAM_5",
                    "Real_ECUs_Required": "ECU1",
                    "CAN_Sim_Needed": "",
                    "Eth_Sim_Needed": "",
                }
            ]
        )
        repository.get_vehicle_program_ecus.return_value = pd.DataFrame(
            [
                {
                    "Vehicle_Program": "VEHICLE_PROGRAM_7",
                    "Applicable_ECUs": "ECU1",
                }
            ]
        )
        repository.get_all_rigs.return_value = pd.DataFrame(
            [
                _rig("RIG_1", real="ECU1", vehicle_program="VEHICLE_PROGRAM_5"),
                _rig("RIG_19", real="ECU1", vehicle_program="VEHICLE_PROGRAM_7"),
            ]
        )

        result = CapabilityMatcherService(repository).match_rigs(
            feature_name="FEATURE_5",
            vehicle_program="VEHICLE_PROGRAM_7",
        )["rigs"]

        self.assertEqual([rig["rig_id"] for rig in result], ["RIG_19", "RIG_1"])
        self.assertFalse(result[0]["is_cross_program"])
        self.assertTrue(result[1]["is_cross_program"])
        self.assertTrue(all(rig["match_score"] == 100.0 for rig in result))

    def test_split_pair_uses_real_subset_even_when_other_rig_covers_all(self) -> None:
        repository = Mock()
        repository.get_all_rigs.return_value = pd.DataFrame(
            [
                _rig("RIG_1", real="ECU1|ECU2", can_sim="ECU25"),
                _rig("RIG_2", real="ECU1", can_sim="ECU2|ECU25"),
                _rig("RIG_3", real="ECU25", can_sim="ECU1|ECU2"),
            ]
        )

        result = CapabilityMatcherService(repository).match_rigs(
            ecus_requested=["ECU1", "ECU2", "ECU25"]
        )

        self.assertIn(
            {
                "rig_ids": ["RIG_1", "RIG_3"],
                "description": (
                    "ECU1 (Real), ECU2 (Real) on RIG_1 AND ECU25 (Real) on RIG_3"
                ),
            },
            result["ecu_split_combinations"],
        )


class SlotSchedulerHoursByRigTests(unittest.TestCase):
    def test_hours_by_rig_matches_standard_and_extended_slot_totals(self) -> None:
        repository = Mock()
        repository.get_all_rigs.return_value = pd.DataFrame(
            {"Rig_ID": ["RIG_1", "RIG_2"]}
        )
        repository.get_bookings.return_value = pd.DataFrame(
            columns=[
                "Rig_ID",
                "Date",
                "Slot_Start_Time",
                "Slot_End_Time",
                "Slot_Type",
                "Booked_By_User",
            ]
        )

        result = SlotSchedulerService(repository).find_free_slots(
            rig_ids=["RIG_1", "RIG_2"],
            start_date="2026-10-15",
            deadline_date="2026-10-15",
        )

        self.assertEqual(
            result["hours_by_rig"],
            {
                "RIG_1": {"standard_hours": 9.0, "extended_hours": 4.0},
                "RIG_2": {"standard_hours": 9.0, "extended_hours": 4.0},
            },
        )
        self.assertEqual(
            sum(item["standard_hours"] for item in result["hours_by_rig"].values()),
            result["total_standard_hours_available"],
        )
        self.assertEqual(
            sum(item["extended_hours"] for item in result["hours_by_rig"].values()),
            result["total_extended_hours_available"],
        )


if __name__ == "__main__":
    unittest.main()
