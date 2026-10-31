"""Tests for tool discipline guards and booking context synchronization."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import streamlit as st
from google.genai import types

from src.agent import orchestrator
from src.agent.tools import discovery_tools, scheduling_tools
from src.services.slot_scheduler import SlotSchedulerService
from src.ui.components import slot_picker_table


class SessionState(dict):
    def __getattr__(self, key: str):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key: str, value) -> None:
        self[key] = value


class SchedulingToolTests(unittest.TestCase):
    def test_availability_tools_replace_deadline_before_start(self) -> None:
        settings = {
            "start_date": "2026-10-18",
            "deadline_date": "2026-10-22",
        }
        state = SessionState(
            {
                "_turn_matched_rigs_by_id": {},
                "_turn_match_targets": [],
                "_turn_last_batch_rig_ids": [],
                "_turn_direct_rig_ids": [],
                "_turn_candidate_slots": [],
                "_turn_slot_durations": [],
                "matched_rigs": [],
                "messages": [],
                "candidate_slots": [],
                "target_duration_hours": 0.0,
                "slot_search_context": {},
                "search_settings": settings,
                "tool_trace": [],
            }
        )
        scheduler = Mock()
        scheduler.find_free_slots.return_value = {
            "standard_slots": [],
            "extended_slots": [],
        }
        with (
            patch.object(st, "session_state", state),
            patch.object(scheduling_tools, "get_repository", return_value=Mock()),
            patch.object(scheduling_tools, "_valid_rig_ids", return_value={"RIG_1"}),
            patch.object(
                scheduling_tools,
                "SlotSchedulerService",
                return_value=scheduler,
            ),
        ):
            scheduling_tools.find_available_slots(
                rig_ids=["RIG_1"],
                duration_hours=1.0,
                deadline_date="2026-10-16",
            )
            scheduling_tools.stage_filtered_slots_for_ui(
                rig_ids=["RIG_1"],
                duration_hours=1.0,
                deadline_date="2026-10-16",
            )

        self.assertEqual(
            [call.kwargs["deadline_date"] for call in scheduler.find_free_slots.call_args_list],
            ["2026-10-22", "2026-10-22"],
        )

    def test_matches_accumulate_and_preserve_best_score_and_labels(self) -> None:
        state = SessionState({"_turn_matched_rigs_by_id": {}, "matched_rigs": []})
        first_rig = {"rig_id": "RIG_1", "match_score": 80.0}
        second_rig = {"rig_id": "RIG_1", "match_score": 100.0}
        matcher = Mock()
        matcher.match_rigs.side_effect = [
            {"rigs": [first_rig]},
            {
                "rigs": [
                    second_rig,
                    {"rig_id": "RIG_2", "match_score": 90.0},
                ]
            },
        ]
        with (
            patch.object(st, "session_state", state),
            patch.object(discovery_tools, "CapabilityMatcherService", return_value=matcher),
            patch.object(discovery_tools, "get_repository", return_value=Mock()),
        ):
            discovery_tools.match_rigs_by_criteria(feature_name="FEATURE_7")
            discovery_tools.match_rigs_by_criteria(feature_name="FEATURE_8")

        self.assertEqual(
            state["_turn_last_batch_rig_ids"],
            ["RIG_1", "RIG_2"],
        )
        self.assertEqual(
            [
                (rig["rig_id"], rig["match_score"], rig["matched_for"])
                for rig in state["_turn_matched_rigs_by_id"].values()
            ],
            [
                ("RIG_1", 100.0, "FEATURE_8"),
                ("RIG_2", 90.0, "FEATURE_8"),
            ],
        )
        self.assertEqual(
            state["_turn_matched_rigs_by_id"]["RIG_1"]["scores_by_target"],
            {"FEATURE_7": 80.0, "FEATURE_8": 100.0},
        )
        self.assertNotIn("matched_for", first_rig)
        self.assertNotIn("matched_for", second_rig)
        self.assertFalse(
            state["_turn_matched_rigs_by_id"]["RIG_1"][
                "shared_across_requests"
            ]
        )

    def test_only_exact_top_matches_are_shared_across_targets(self) -> None:
        state = SessionState({"_turn_matched_rigs_by_id": {}, "matched_rigs": []})
        matcher = Mock()
        matcher.match_rigs.side_effect = [
            {"rigs": [{"rig_id": "RIG_1", "match_score": 100.0}]},
            {"rigs": [{"rig_id": "RIG_1", "match_score": 100.0}]},
        ]
        with (
            patch.object(st, "session_state", state),
            patch.object(discovery_tools, "CapabilityMatcherService", return_value=matcher),
            patch.object(discovery_tools, "get_repository", return_value=Mock()),
        ):
            discovery_tools.match_rigs_by_criteria(feature_name="FEATURE_7")
            result = discovery_tools.match_rigs_by_criteria(
                feature_name="FEATURE_8"
            )

        accumulated = state["_turn_matched_rigs_by_id"]["RIG_1"]
        self.assertEqual(
            accumulated["scores_by_target"],
            {"FEATURE_7": 100.0, "FEATURE_8": 100.0},
        )
        self.assertEqual(accumulated["matched_for"], "FEATURE_7 & FEATURE_8")
        self.assertTrue(accumulated["shared_across_requests"])
        self.assertEqual(result["shared_across_requests"], ["RIG_1"])

    def test_discovery_accumulates_only_top_three_rigs_per_category(self) -> None:
        state = SessionState({"_turn_matched_rigs_by_id": {}, "matched_rigs": []})
        matcher = Mock()
        matcher.match_rigs.return_value = {
            "rigs": [
                {"rig_id": f"RIG_{number}", "match_score": 100.0 - number}
                for number in range(1, 6)
            ]
        }
        with (
            patch.object(st, "session_state", state),
            patch.object(discovery_tools, "CapabilityMatcherService", return_value=matcher),
            patch.object(discovery_tools, "get_repository", return_value=Mock()),
        ):
            result = discovery_tools.match_rigs_by_criteria(feature_name="FEATURE_7")

        self.assertEqual(
            [rig["rig_id"] for rig in result["rigs"]],
            ["RIG_1", "RIG_2", "RIG_3"],
        )
        self.assertEqual(
            list(state["_turn_matched_rigs_by_id"]),
            ["RIG_1", "RIG_2", "RIG_3"],
        )

    def test_discovery_compresses_llm_payload_but_keeps_full_ui_rig(self) -> None:
        state = SessionState({"_turn_matched_rigs_by_id": {}, "matched_rigs": []})
        matcher = Mock()
        matcher.match_rigs.return_value = {
            "rigs": [
                {
                    "rig_id": "RIG_1",
                    "Rig_ID": "RIG_1",
                    "Vehicle_Program": "VEHICLE_PROGRAM_1",
                    "Rig_Platform": "Vector",
                    "Rig_Domain": "DOMAIN_1",
                    "Rig_Engineer": "ENG_1",
                    "Real_Connected_Components": "ECU1|ECU2",
                    "CAN_Sim_ECUs": "ECU3",
                    "Eth_Sim_ECUs": "",
                    "real_ecus": ["ECU1", "ECU2"],
                    "can_sim_ecus": ["ECU3"],
                    "eth_sim_ecus": [],
                    "match_score": 100.0,
                    "matched_for": "FEATURE_7",
                    "ecu_breakdown": [
                        {"required": "Real", "available": "Real"},
                        {"required": "Real", "available": "Missing"},
                    ],
                }
            ]
        }
        with (
            patch.object(st, "session_state", state),
            patch.object(
                discovery_tools,
                "CapabilityMatcherService",
                return_value=matcher,
            ),
            patch.object(discovery_tools, "get_repository", return_value=Mock()),
        ):
            result = discovery_tools.match_rigs_by_criteria(
                feature_name="FEATURE_7"
            )

        rig_for_llm = result["rigs"][0]
        self.assertNotIn("ranked_rigs", result)
        for field in (
            "Real_Connected_Components",
            "CAN_Sim_ECUs",
            "Eth_Sim_ECUs",
            "Rig_ID",
            "Vehicle_Program",
            "Rig_Domain",
            "Rig_Platform",
            "Rig_Engineer",
        ):
            self.assertNotIn(field, rig_for_llm)
        self.assertEqual(
            rig_for_llm["ecu_breakdown"],
            [{"required": "Real", "available": "Missing"}],
        )
        self.assertIn(
            "Real_Connected_Components",
            state["matched_rigs"][0],
        )

    def test_cross_program_fallback_is_not_counted_as_top_three_overlap(self) -> None:
        state = SessionState({"_turn_matched_rigs_by_id": {}, "matched_rigs": []})
        matcher = Mock()
        matcher.match_rigs.side_effect = [
            {
                "rigs": [
                    {
                        "rig_id": f"RIG_{number}",
                        "match_score": 100.0,
                        "is_cross_program": number == 4,
                        "criterion_scores": {"FEATURE_7": 100.0},
                    }
                    for number in range(1, 5)
                ],
                "request_groups": {
                    "FEATURE_7": ["RIG_1", "RIG_2", "RIG_3", "RIG_4"]
                },
            },
            {
                "rigs": [
                    {
                        "rig_id": "RIG_4",
                        "match_score": 100.0,
                        "criterion_scores": {"FEATURE_8": 100.0},
                    }
                ],
                "request_groups": {"FEATURE_8": ["RIG_4"]},
            },
        ]
        with (
            patch.object(st, "session_state", state),
            patch.object(discovery_tools, "CapabilityMatcherService", return_value=matcher),
            patch.object(discovery_tools, "get_repository", return_value=Mock()),
        ):
            discovery_tools.match_rigs_by_criteria(feature_name="FEATURE_7")
            result = discovery_tools.match_rigs_by_criteria(
                feature_name="FEATURE_8"
            )

        rig_four = state["_turn_matched_rigs_by_id"]["RIG_4"]
        self.assertEqual(
            rig_four["scores_by_target"],
            {"FEATURE_7": 100.0, "FEATURE_8": 100.0},
        )
        self.assertEqual(rig_four["top3_targets"], ["FEATURE_8"])
        self.assertFalse(rig_four["shared_across_requests"])
        self.assertNotIn("RIG_4", result["shared_across_requests"])
        self.assertEqual(
            state["matched_rigs"],
            list(state["_turn_matched_rigs_by_id"].values()),
        )

    def test_find_slots_accumulates_candidates_durations_and_rig_context(self) -> None:
        state = SessionState({
            "_turn_matched_rigs_by_id": {
                "RIG_1": {"rig_id": "RIG_1", "matched_for": "FEATURE_7"},
                "RIG_2": {"rig_id": "RIG_2", "matched_for": "FEATURE_8"},
                "RIG_3": {"rig_id": "RIG_3", "matched_for": "FEATURE_8"},
            },
            "_turn_match_targets": ["FEATURE_7", "FEATURE_8"],
            "_turn_last_batch_rig_ids": ["RIG_2", "RIG_3"],
            "_turn_candidate_slots": [],
            "_turn_slot_durations": [],
            "matched_rigs": [
                {"rig_id": "RIG_1", "matched_for": "FEATURE_7"},
                {"rig_id": "RIG_2", "matched_for": "FEATURE_8"},
                {"rig_id": "RIG_3", "matched_for": "FEATURE_8"},
            ],
            "messages": [
                {
                    "role": "user",
                    "content": "Test FEATURE_7 and FEATURE_8 for 4 hours each.",
                }
            ],
            "candidate_slots": [],
            "target_duration_hours": 0.0,
            "slot_search_context": {"rig_ids": ["RIG_OLD"]},
            "search_settings": {},
            "tool_trace": [],
        })
        shared_slot = {
            "rig_id": "RIG_2",
            "date": "2026-10-20",
            "start_time": "09:00",
            "end_time": "13:00",
            "window_type": "Standard Shift",
            "duration_hrs": 4.0,
        }
        scheduler = Mock()
        scheduler.find_free_slots.side_effect = [
            {
                "standard_slots": [shared_slot],
                "extended_slots": [],
            },
            {
                "standard_slots": [
                    shared_slot,
                    {
                        **shared_slot,
                        "rig_id": "RIG_1",
                    },
                ],
                "extended_slots": [],
            },
        ]
        with (
            patch.object(st, "session_state", state),
            patch.object(
                scheduling_tools,
                "SlotSchedulerService",
                return_value=scheduler,
            ),
            patch.object(scheduling_tools, "get_repository", return_value=Mock()),
            patch.object(
                scheduling_tools,
                "_valid_rig_ids",
                return_value={"RIG_1", "RIG_2", "RIG_3"},
            ),
        ):
            scheduling_tools.find_available_slots(
                rig_ids=["RIG_2"],
                duration_hours=4,
            )
            scheduling_tools.find_available_slots(
                rig_ids=["RIG_1", "RIG_2"],
                duration_hours=4,
            )

        calls = scheduler.find_free_slots.call_args_list
        self.assertEqual(calls[0].kwargs["rig_ids"], ["RIG_2", "RIG_1", "RIG_3"])
        self.assertEqual(calls[1].kwargs["rig_ids"], ["RIG_1", "RIG_2", "RIG_3"])
        self.assertEqual(
            state["_turn_slot_durations"],
            [
                (("RIG_2",), 4.0),
                (("RIG_1", "RIG_2"), 4.0),
            ],
        )
        self.assertEqual(state["target_duration_hours"], 8.0)
        self.assertEqual(len(state["candidate_slots"]), 2)
        self.assertEqual(
            state["slot_search_context"]["rig_ids"],
            ["RIG_OLD", "RIG_2", "RIG_1", "RIG_3"],
        )

    def test_initial_availability_search_includes_all_matched_rigs(self) -> None:
        state = SessionState({
            "matched_rigs": [
                {"rig_id": "RIG_1"},
                {"rig_id": "RIG_2"},
                {"Rig_ID": "RIG_3"},
            ],
            "search_settings": {},
        })
        result = {
            "standard_slots": [],
            "extended_slots": [],
        }
        scheduler = Mock()
        scheduler.find_free_slots.return_value = result
        with (
            patch.object(st, "session_state", state),
            patch.object(
                scheduling_tools,
                "SlotSchedulerService",
                return_value=scheduler,
            ),
            patch.object(scheduling_tools, "get_repository", return_value=Mock()),
            patch.object(
                scheduling_tools,
                "_valid_rig_ids",
                return_value={"RIG_1", "RIG_2", "RIG_3"},
            ),
        ):
            scheduling_tools.find_available_slots(
                rig_ids=["RIG_2", "RIG_2"],
                duration_hours=4,
            )

        self.assertEqual(
            scheduler.find_free_slots.call_args.kwargs["rig_ids"],
            ["RIG_2", "RIG_1", "RIG_3"],
        )

    def test_single_slot_search_in_multi_target_turn_includes_each_matched_group(self) -> None:
        state = SessionState({
            "_turn_match_targets": ["RIG_10", "FEATURE_3 + VEHICLE_PROGRAM_1"],
            "_turn_direct_rig_ids": ["RIG_10"],
            "_turn_matched_rigs_by_id": {
                "RIG_10": {"rig_id": "RIG_10"},
                "RIG_3": {"rig_id": "RIG_3"},
            },
            "_turn_last_batch_rig_ids": ["RIG_1", "RIG_2", "RIG_3"],
            "matched_rigs": [
                {"rig_id": "RIG_10"},
                {"rig_id": "RIG_3"},
            ],
            "search_settings": {},
        })
        scheduler = Mock()
        scheduler.find_free_slots.return_value = {
            "standard_slots": [],
            "extended_slots": [],
        }
        with (
            patch.object(st, "session_state", state),
            patch.object(
                scheduling_tools,
                "SlotSchedulerService",
                return_value=scheduler,
            ),
            patch.object(scheduling_tools, "get_repository", return_value=Mock()),
            patch.object(
                scheduling_tools,
                "_valid_rig_ids",
                return_value={"RIG_1", "RIG_2", "RIG_3", "RIG_10"},
            ),
        ):
            scheduling_tools.find_available_slots(
                rig_ids=["RIG_10"],
                duration_hours=4,
            )

        self.assertEqual(
            scheduler.find_free_slots.call_args.kwargs["rig_ids"],
            ["RIG_10", "RIG_3"],
        )

    def test_availability_search_does_not_merge_unmatched_ids(self) -> None:
        state = SessionState({
            "matched_rigs": [{"rig_id": "RIG_1"}, {"rig_id": "RIG_2"}],
            "search_settings": {},
        })
        scheduler = Mock()
        scheduler.find_free_slots.return_value = {
            "standard_slots": [],
            "extended_slots": [],
        }
        with (
            patch.object(st, "session_state", state),
            patch.object(
                scheduling_tools,
                "SlotSchedulerService",
                return_value=scheduler,
            ),
            patch.object(scheduling_tools, "get_repository", return_value=Mock()),
            patch.object(
                scheduling_tools,
                "_valid_rig_ids",
                return_value={"RIG_1", "RIG_2", "RIG_99"},
            ),
        ):
            scheduling_tools.find_available_slots(
                rig_ids=["RIG_99"],
                duration_hours=4,
            )

        self.assertEqual(
            scheduler.find_free_slots.call_args.kwargs["rig_ids"],
            ["RIG_99"],
        )

    def test_combined_duration_is_not_double_counted_for_each_calls(self) -> None:
        records = [
            (("RIG_1", "RIG_2"), 8.0),
            (("RIG_3", "RIG_4"), 8.0),
        ]
        messages = [
            {
                "role": "user",
                "content": "Test FEATURE_7 and FEATURE_8 for 4 hours each.",
            }
        ]

        total = scheduling_tools._combined_turn_duration(
            records,
            messages,
        )

        self.assertEqual(total, 8.0)

    def test_combined_duration_sums_distinct_and_per_target_hours(self) -> None:
        distinct_total = scheduling_tools._combined_turn_duration(
            [(("RIG_1",), 3.0), (("RIG_6",), 2.0)],
            [],
            "Test FEATURE_1 for 3 hours and book VEHICLE_PROGRAM_6 for 2 hours.",
        )
        per_target_total = scheduling_tools._combined_turn_duration(
            [(("RIG_1",), 4.0), (("RIG_2",), 4.0)],
            [],
            "Test FEATURE_1 and FEATURE_2 for 4 hours each.",
        )
        already_combined_total = scheduling_tools._combined_turn_duration(
            [(("RIG_1",), 8.0), (("RIG_2",), 8.0)],
            [],
            "Test FEATURE_1 and FEATURE_2 for 4 hours each.",
        )

        self.assertEqual(distinct_total, 5.0)
        self.assertEqual(per_target_total, 8.0)
        self.assertEqual(already_combined_total, 8.0)

    def test_combined_duration_handles_per_ecu_plus_separate_program(self) -> None:
        prompt = (
            "I want a VEHICLE_PROGRAM_3 rig for 2 hours, and I also want to "
            "test ECU21 and ECU22 for 1 hour each."
        )
        self.assertEqual(
            scheduling_tools._combined_turn_duration(
                [(("RIG_7",), 2.0), (("RIG_1", "RIG_2"), 2.0)],
                [],
                prompt,
            ),
            4.0,
        )

    def test_rig_id_sanitization_rejects_unknown_ids(self) -> None:
        self.assertEqual(
            scheduling_tools._sanitize_rig_ids(
                ["Dispatch_RIG_30", "RIG_999", "RIG_30"],
                {"RIG_30"},
            ),
            ["RIG_30"],
        )

    def test_rig_id_sanitization_strips_leading_zeroes(self) -> None:
        self.assertEqual(
            scheduling_tools._sanitize_rig_ids(
                ["RIG_004", "Dispatch_RIG_02"],
                {"RIG_2", "RIG_4"},
            ),
            ["RIG_4", "RIG_2"],
        )

    def test_slots_are_enriched_with_feature_and_unmatched_ids_are_dropped(self) -> None:
        state = SessionState({
            "matched_rigs": [
                {
                    "rig_id": "RIG_30",
                    "matched_for": "FEATURE_8",
                    "match_score": 100.0,
                    "platform": "Vector",
                    "vehicle_program": "VEHICLE_PROGRAM_10",
                    "rig_engineer": "ENG_29",
                }
            ],
        })
        slots = [
            {
                "rig_id": "RIG_30",
                "date": "2026-10-20",
                "start_time": "09:00",
                "end_time": "10:00",
                "window_type": "Standard Shift",
            },
            {
                "rig_id": "RIG_999",
                "date": "2026-10-20",
                "start_time": "09:00",
                "end_time": "10:00",
                "window_type": "Standard Shift",
            },
        ]
        with patch.object(st, "session_state", state):
            enriched = scheduling_tools._enrich_slots(slots)

        self.assertEqual(len(enriched), 1)
        self.assertEqual(
            enriched[0]["rig_details"],
            "FEATURE_8 | 100.0% Match | Vector | VEHICLE_PROGRAM_10 | ENG_29",
        )

    def test_tool_availability_payload_omits_extended_lists_unless_requested(self) -> None:
        availability = {
            "standard_slots": [{"rig_id": "RIG_1"}],
            "extended_slots": [{"rig_id": f"RIG_{number}"} for number in range(50)],
            "hours_by_rig": {"RIG_1": {"standard_hours": 9, "extended_hours": 4}},
            "total_standard_hours_available": 9,
            "total_extended_hours_available": 4,
            "total_with_extended_hours": 13,
            "rig_conflicts": [],
            "search_end_date": "2026-10-23",
        }

        standard_payload = scheduling_tools._tool_availability_payload(
            availability,
            include_extended=False,
        )
        extended_payload = scheduling_tools._tool_availability_payload(
            availability,
            include_extended=True,
        )
        self.assertNotIn("extended_slots", standard_payload)
        self.assertNotIn("extended_slots_preview", standard_payload)
        self.assertEqual(len(extended_payload["extended_slots"]), 50)
        self.assertEqual(len(extended_payload["extended_slots_preview"]), 50)

    def test_slot_details_show_exact_scores_for_each_target(self) -> None:
        state = SessionState({
            "matched_rigs": [
                {
                    "rig_id": "RIG_30",
                    "matched_for": "FEATURE_8",
                    "scores_by_target": {
                        "FEATURE_8": 100.0,
                        "FEATURE_7": 66.7,
                    },
                    "platform": "NI",
                    "vehicle_program": "VEHICLE_PROGRAM_10",
                    "rig_engineer": "ENG_30",
                }
            ],
        })
        slots = [{
            "rig_id": "RIG_30",
            "date": "2026-10-20",
            "start_time": "09:00",
            "end_time": "10:00",
            "window_type": "Standard Shift",
        }]

        with patch.object(st, "session_state", state):
            enriched = scheduling_tools._enrich_slots(slots)

        self.assertEqual(
            enriched[0]["rig_details"],
            "FEATURE_8 (100.0% Match) & FEATURE_7 (66.7% Match) | "
            "NI | VEHICLE_PROGRAM_10 | ENG_30",
        )


class SlotSchedulerRigValidationTests(unittest.TestCase):
    def test_sanitizes_prefixed_ids_and_drops_unknown_rigs(self) -> None:
        repository = Mock()
        repository.get_all_rigs.return_value = pd.DataFrame(
            {"Rig_ID": ["RIG_30", "RIG_1"]}
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
            rig_ids=["Dispatch_RIG_30", "RIG_999", "RIG_30"],
            start_date="2026-10-15",
            deadline_date="2026-10-15",
        )

        self.assertEqual(list(result["hours_by_rig"]), ["RIG_30"])
        self.assertTrue(
            all(slot["rig_id"] == "RIG_30" for slot in result["standard_slots"])
        )

    def test_normalizes_zero_padded_ids_before_validation(self) -> None:
        repository = Mock()
        repository.get_all_rigs.return_value = pd.DataFrame(
            {"Rig_ID": ["RIG_4", "RIG_2"]}
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
            rig_ids=["RIG_04", "Dispatch_RIG_02"],
            start_date="2026-10-15",
            deadline_date="2026-10-15",
        )

        self.assertEqual(list(result["hours_by_rig"]), ["RIG_4", "RIG_2"])


class BookingHistoryTests(unittest.TestCase):
    def test_gemini_booking_notice_records_ids_type_and_each_interval(self) -> None:
        state: SessionState = SessionState({"agent_history": []})
        bookings = [
            {
                "rig_id": "RIG_1",
                "date": "2026-10-19",
                "start_time": "09:00",
                "end_time": "11:00",
            },
            {
                "rig_id": "RIG_2",
                "date": "2026-10-20",
                "start_time": "13:00",
                "end_time": "15:00",
            },
        ]
        with (
            patch.object(st, "session_state", state),
            patch.object(slot_picker_table, "LLM_PROVIDER", "gemini"),
        ):
            slot_picker_table._append_booking_history_notice(
                bookings,
                ["BK_101", "BK_102"],
                "MANUAL_TESTING",
            )

        self.assertEqual(len(state["agent_history"]), 2)
        content = state["agent_history"][0]
        self.assertIsInstance(content, types.Content)
        notice = content.parts[0].text
        for value in (
            "BK_101",
            "BK_102",
            "RIG_1",
            "RIG_2",
            "2026-10-19",
            "2026-10-20",
            "09:00",
            "11:00",
            "13:00",
            "15:00",
            "selected_type=MANUAL_TESTING",
        ):
            self.assertIn(value, notice)
        confirmation = state["agent_history"][1]
        self.assertEqual(confirmation.role, "model")
        self.assertIn("Booking confirmed: BK_101, BK_102", confirmation.parts[0].text)


class GeminiThinkingBudgetTests(unittest.TestCase):
    def test_empty_response_after_staging_returns_summary(self) -> None:
        chat = Mock()
        chat.send_message.return_value = SimpleNamespace(text="")
        chat.get_history.return_value = []
        client = Mock()
        client.chats.create.return_value = chat
        state = SessionState(
            {
                "benchmark_trace": None,
                "tool_trace": [],
                "agent_history": [],
                "candidate_slots": [
                    {"rig_id": "RIG_1"},
                    {"rig_id": "RIG_2"},
                ],
                "matched_rigs": [{"rig_id": "RIG_1"}],
            }
        )
        with (
            patch.object(st, "session_state", state),
            patch.object(orchestrator.genai, "Client", return_value=client),
        ):
            agent = orchestrator.AgentOrchestrator("test-api-key")
            response = agent.respond("Hello")

        self.assertIn("1 compatible rig(s) (RIG_1)", response)
        self.assertIn("staged 2 available time slot(s)", response)

    def test_turn_accumulators_are_reset_immediately_before_gemini_send(self) -> None:
        state = SessionState({
            "benchmark_trace": None,
            "tool_trace": [],
            "agent_history": [],
            "_turn_matched_rigs_by_id": {"RIG_OLD": {"rig_id": "RIG_OLD"}},
            "_turn_last_batch_rig_ids": ["RIG_OLD"],
            "_turn_candidate_slots": [{"rig_id": "RIG_OLD"}],
            "_turn_slot_durations": [(("RIG_OLD",), 8.0)],
            "_turn_match_targets": ["FEATURE_OLD"],
            "_turn_user_message": "old turn",
        })
        chat = Mock()

        def send_message(message: str):
            self.assertEqual(state["_turn_matched_rigs_by_id"], {})
            self.assertEqual(state["_turn_last_batch_rig_ids"], [])
            self.assertEqual(state["_turn_candidate_slots"], [])
            self.assertEqual(state["_turn_slot_durations"], [])
            self.assertEqual(state["_turn_match_targets"], [])
            self.assertEqual(state["_turn_direct_rig_ids"], [])
            self.assertEqual(state["_turn_user_message"], message)
            return SimpleNamespace(text="Ready.")

        chat.send_message.side_effect = send_message
        chat.get_history.return_value = []
        client = Mock()
        client.chats.create.return_value = chat
        with (
            patch.object(st, "session_state", state),
            patch.object(orchestrator.genai, "Client", return_value=client),
        ):
            agent = orchestrator.AgentOrchestrator("test-api-key")
            self.assertEqual(agent.respond("Hello"), "Ready.")

    def test_configured_thinking_budget_is_passed_to_gemini(self) -> None:
        chat = Mock()
        chat.send_message.return_value = SimpleNamespace(text="Ready.")
        chat.get_history.return_value = []
        client = Mock()
        client.chats.create.return_value = chat
        state = SessionState({"benchmark_trace": None, "tool_trace": [], "agent_history": []})
        with (
            patch.object(st, "session_state", state),
            patch.object(orchestrator, "GEMINI_THINKING_BUDGET", 0),
            patch.object(orchestrator.genai, "Client", return_value=client),
        ):
            agent = orchestrator.AgentOrchestrator("test-api-key")
            self.assertEqual(agent.respond("Hello"), "Ready.")

        config = client.chats.create.call_args.kwargs["config"]
        self.assertIsInstance(config.thinking_config, types.ThinkingConfig)
        self.assertEqual(config.thinking_config.thinking_budget, 0)

    def test_missing_duration_disables_tools_and_adds_gatekeeper_instruction(self) -> None:
        chat = Mock()
        chat.send_message.return_value = SimpleNamespace(
            text="How many hours do you need for the test?"
        )
        chat.get_history.return_value = []
        client = Mock()
        client.chats.create.return_value = chat
        state = SessionState({
            "benchmark_trace": None,
            "tool_trace": [],
            "agent_history": [],
            "messages": [
                {
                    "role": "user",
                    "content": "I want to test FEATURE_1 on VEHICLE_PROGRAM_1.",
                }
            ],
            "target_duration_hours": 0,
        })
        with (
            patch.object(st, "session_state", state),
            patch.object(orchestrator.genai, "Client", return_value=client),
        ):
            agent = orchestrator.AgentOrchestrator("test-api-key")
            response = agent.respond(
                "I want to test FEATURE_1 on VEHICLE_PROGRAM_1."
            )

        self.assertIn("hours", response)
        config = client.chats.create.call_args.kwargs["config"]
        self.assertEqual(config.tools, [])
        self.assertIn("Ask ONLY", config.system_instruction)

    def test_explicit_duration_in_prior_user_message_keeps_tools_available(self) -> None:
        chat = Mock()
        chat.send_message.return_value = SimpleNamespace(text="Searching now.")
        chat.get_history.return_value = []
        client = Mock()
        client.chats.create.return_value = chat
        state = SessionState({
            "benchmark_trace": None,
            "tool_trace": [],
            "agent_history": [],
            "messages": [
                {
                    "role": "user",
                    "content": "I need a rig for 2.5 hours.",
                }
            ],
            "target_duration_hours": 0,
        })
        with (
            patch.object(st, "session_state", state),
            patch.object(orchestrator.genai, "Client", return_value=client),
        ):
            agent = orchestrator.AgentOrchestrator("test-api-key")
            agent.respond("Find an option for that duration.")

        config = client.chats.create.call_args.kwargs["config"]
        self.assertTrue(config.tools)

    def test_existing_positive_session_duration_keeps_tools_available(self) -> None:
        state = SessionState({
            "messages": [
                {"role": "user", "content": "Find a rig for FEATURE_1."},
            ],
            "target_duration_hours": 2.0,
        })
        with patch.object(st, "session_state", state):
            self.assertFalse(
                orchestrator._needs_duration_gatekeeper(
                    "Find a rig for FEATURE_1.", state["messages"]
                )
            )


if __name__ == "__main__":
    unittest.main()
