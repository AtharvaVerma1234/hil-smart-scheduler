"""Regression coverage for production-oriented ID, duration, and persistence fixes."""

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import streamlit as st
from unittest.mock import MagicMock, Mock

from src.agent import orchestrator
from src.agent.tools import discovery_tools, scheduling_tools
from src.repositories import get_repository
from src.repositories.csv_repository import CSVHILRepository
from src.services.capability_matcher import CapabilityMatcherService
from src.services.slot_scheduler import SlotSchedulerService
from src.utils.parsers import natural_sort_key, resolve_rig_id
from src.ui.components import chat_panel, slot_picker_table
from src.ui.components.chat_panel import _highlight_entities
from src.ui.components.sidebar import (
    _five_active_dates,
    _on_shift_slider_change,
    _toggle_left_sidebar,
    render_sidebar,
)


class SessionState(dict):
    def __getattr__(self, key: str):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key: str, value) -> None:
        self[key] = value


class ProductionRigIdentifierTests(unittest.TestCase):
    def test_resolves_catalog_ids_with_padding_and_llm_prefixes(self) -> None:
        valid_ids = {
            "RIG_4",
            "RIG_30",
            "SCALEXIO_ADAS_01",
            "ADAS_01",
            "TAMS-2564",
            "MODEL_X_INFOTAINMENT-3056",
        }
        self.assertEqual(resolve_rig_id("RIG_04", valid_ids), "RIG_4")
        self.assertEqual(resolve_rig_id("Dispatch_RIG_30", valid_ids), "RIG_30")
        self.assertEqual(
            resolve_rig_id("Bench_SCALEXIO_ADAS_001", valid_ids),
            "SCALEXIO_ADAS_01",
        )
        self.assertEqual(resolve_rig_id("adas_001", valid_ids), "ADAS_01")
        self.assertEqual(resolve_rig_id("TAMS-2564", valid_ids), "TAMS-2564")
        self.assertEqual(
            resolve_rig_id("MODEL_X_INFOTAINMENT-3056", valid_ids),
            "MODEL_X_INFOTAINMENT-3056",
        )

    def test_without_catalog_only_normalizes_simple_numeric_suffix(self) -> None:
        self.assertEqual(resolve_rig_id("RIG_04"), "RIG_4")
        self.assertEqual(resolve_rig_id("SCALEXIO_ADAS_01"), "SCALEXIO_ADAS_01")
        self.assertEqual(resolve_rig_id(""), "")

    def test_natural_sort_handles_mixed_numeric_and_alpha_rig_ids(self) -> None:
        rig_ids = [
            "VT_BENCH_A",
            "SCALEXIO_ADAS_10",
            "TAMS-2564",
            "SCALEXIO_ADAS_2",
            "MODEL_X_INFOTAINMENT-3056",
        ]
        ordered = sorted(rig_ids, key=natural_sort_key)
        self.assertEqual(
            ordered,
            [
                "MODEL_X_INFOTAINMENT-3056",
                "SCALEXIO_ADAS_2",
                "SCALEXIO_ADAS_10",
                "TAMS-2564",
                "VT_BENCH_A",
            ],
        )

        scored = [
            {
                "rig_id": rig_id,
                "match_score": 80.0,
                "is_cross_program": False,
                "ecu_breakdown": [],
            }
            for rig_id in rig_ids
        ]
        self.assertEqual(
            [
                item["rig_id"]
                for item in CapabilityMatcherService._sort_results(scored)
            ],
            ordered,
        )

    def test_scheduler_accepts_custom_catalog_rig_id(self) -> None:
        class Repository:
            def get_all_rigs(self) -> pd.DataFrame:
                return pd.DataFrame({"Rig_ID": ["SCALEXIO_ADAS_01"]})

            def get_bookings(self) -> pd.DataFrame:
                return pd.DataFrame(
                    columns=[
                        "Rig_ID",
                        "Date",
                        "Slot_Start_Time",
                        "Slot_End_Time",
                        "Slot_Type",
                        "Booked_By_User",
                    ]
                )

        result = SlotSchedulerService(Repository()).find_free_slots(
            ["Bench_SCALEXIO_ADAS_001"],
            start_date="2026-10-15",
            deadline_date="2026-10-15",
        )
        self.assertEqual(list(result["hours_by_rig"]), ["SCALEXIO_ADAS_01"])


class ProductionUiRenderingTests(unittest.TestCase):
    def test_collapsed_sidebar_preserves_active_filter_settings(self) -> None:
        state = SessionState(
            {
                "left_sidebar_collapsed": False,
                "saved_filter_timezone": "Europe/Berlin",
                "filter_shift_range": ("08:00", "17:30"),
                "filter_start_date": "2026-10-15",
                "filter_allow_weekends": True,
                "filter_include_extended": True,
                "search_settings": {"existing": "settings"},
            }
        )
        container = MagicMock()
        with (
            patch.object(st, "session_state", state),
            patch.object(st, "context", Mock(timezone="UTC")),
            patch.object(st, "button"),
        ):
            _toggle_left_sidebar()
            active_filters = render_sidebar(container)

        self.assertTrue(state["left_sidebar_collapsed"])
        self.assertEqual(active_filters["timezone"], "Europe/Berlin")
        self.assertEqual(active_filters["shift_start"], "08:00")
        self.assertEqual(active_filters["shift_end"], "17:30")
        self.assertEqual(active_filters["simulated_date"], "2026-10-15")
        self.assertEqual(active_filters["deadline_date"], "2026-10-19")

    def test_shift_slider_callback_synchronizes_valid_range(self) -> None:
        state = SessionState({"filter_shift_range_widget": ("08:00", "16:30")})
        with patch.object(st, "session_state", state):
            _on_shift_slider_change()

        self.assertEqual(state["filter_shift_range"], ("08:00", "16:30"))
        self.assertEqual(
            state["filter_shift_range_widget"],
            ("08:00", "16:30"),
        )

    def test_calendar_slider_interval_survives_chat_editor_stale_values(self) -> None:
        slot = {
            "rig_id": "RIG_1",
            "date": "2026-10-15",
            "start_time": "14:00",
            "end_time": "16:30",
            "orig_start_time": "14:00",
            "orig_end_time": "18:00",
        }
        state = SessionState(
            {
                "candidate_slots": [slot],
                "selected_slot_keys": ["RIG_1|2026-10-15|14:00|18:00"],
                "_calendar_slider_just_updated": True,
            }
        )
        stale_frame = pd.DataFrame(
            [
                {
                    "Select": True,
                    "rig_id": "RIG_1",
                    "Rig_Details": "details",
                    "date": "2026-10-15 (Thursday)",
                    "start_time": "14:00",
                    "end_time": "16:00",
                    "duration_hrs": 2.0,
                    "window_type": "Standard",
                    "orig_start_time": "14:00",
                    "orig_end_time": "18:00",
                    "slot_key": "RIG_1|2026-10-15|14:00|18:00",
                }
            ]
        )
        with (
            patch.object(st, "session_state", state),
            patch.object(st, "data_editor", return_value=stale_frame),
        ):
            chat_panel.render_chat_slot_selector()

        self.assertEqual(slot["start_time"], "14:00")
        self.assertEqual(slot["end_time"], "16:30")
        self.assertNotIn("_calendar_slider_just_updated", state)

    def test_calendar_window_has_five_active_days(self) -> None:
        start = date(2026, 10, 16)
        weekdays = _five_active_dates(start, allow_weekends=False)
        weekend_days = _five_active_dates(start, allow_weekends=True)

        self.assertEqual(len(weekdays), 5)
        self.assertTrue(all(day.weekday() < 5 for day in weekdays))
        self.assertEqual(weekdays[0], start)
        self.assertEqual(len(weekend_days), 5)
        self.assertEqual(weekend_days, [date(2026, 10, day) for day in range(16, 21)])
        self.assertEqual(
            slot_picker_table._active_dates(start, allow_weekends=False),
            weekdays,
        )

    def test_highlight_entities_preserves_code_spans(self) -> None:
        rendered = _highlight_entities(
            "Test FEATURE_12 for 2 hours with `ECU3` and ```RIG_4```."
        )
        self.assertIn(
            '<span style="color: #E6DB74; font-weight: 600;">FEATURE_12</span>',
            rendered,
        )
        self.assertIn(
            '<span style="color: #E6DB74; font-weight: 600;">2 hours</span>',
            rendered,
        )
        self.assertIn("`ECU3`", rendered)
        self.assertIn("```RIG_4```", rendered)
        self.assertNotIn("<span", rendered.split("`ECU3`")[1].split("```RIG_4```")[0])

    def test_timeline_has_selected_and_available_remainder_without_gaps(self) -> None:
        selected_slots = [
            {
                "rig_id": "RIG_1",
                "date": "2026-10-15",
                "start_time": "14:00",
                "end_time": "16:00",
            }
        ]
        blocks = slot_picker_table.build_rig_day_timeline(
            "RIG_1",
            "2026-10-15",
            "14:00",
            "18:00",
            pd.DataFrame(),
            selected_slots,
        )
        self.assertEqual(
            [(block["status"], block["start_time"], block["end_time"]) for block in blocks],
            [
                ("Selected", "14:00", "16:00"),
                ("Available", "16:00", "18:00"),
            ],
        )
        self.assertEqual([block["duration_hrs"] for block in blocks], [2.0, 2.0])
        self.assertEqual(
            blocks[0]["end_time"],
            blocks[1]["start_time"],
            "Consecutive blocks must have no empty time gap.",
        )

    def test_auto_select_proposed_split_trims_final_slot_to_target(self) -> None:
        slots = [
            {
                "rig_id": "RIG_1",
                "date": "2026-10-15",
                "start_time": "09:00",
                "end_time": "11:00",
                "orig_start_time": "09:00",
                "orig_end_time": "11:00",
            },
            {
                "rig_id": "RIG_1",
                "date": "2026-10-15",
                "start_time": "13:00",
                "end_time": "16:00",
                "orig_start_time": "13:00",
                "orig_end_time": "16:00",
            },
        ]
        selected = scheduling_tools._auto_select_proposed_split(slots, 2.5)
        self.assertEqual(
            selected,
            [
                "RIG_1|2026-10-15|09:00|11:00",
                "RIG_1|2026-10-15|13:00|16:00",
            ],
        )
        self.assertEqual(slots[0]["duration_hrs"], 2.0)
        self.assertEqual(slots[1]["start_time"], "13:00")
        self.assertEqual(slots[1]["end_time"], "13:30")
        self.assertEqual(slots[1]["duration_hrs"], 0.5)

    def test_calendar_resize_updates_slot_and_slider_state(self) -> None:
        slot = {
            "rig_id": "RIG_1",
            "date": "2026-10-15",
            "start_time": "14:00",
            "end_time": "16:00",
            "orig_start_time": "14:00",
            "orig_end_time": "18:00",
        }
        state = {
            "candidate_slots": [slot],
            "resize_test_slider": ("14:00", "16:00"),
        }
        with patch.object(st, "session_state", state):
            slot_picker_table._resize_selected_slot(
                "RIG_1|2026-10-15|14:00|18:00",
                "resize_test",
                30,
            )
        self.assertEqual(slot["start_time"], "14:00")
        self.assertEqual(slot["end_time"], "16:30")
        self.assertEqual(slot["duration_hrs"], 2.5)
        self.assertEqual(state["resize_test_slider"], ("14:00", "16:30"))

    def test_calendar_expand_modal_toggle_and_prefixed_resizer_sync(self) -> None:
        slot = {
            "rig_id": "RIG_1",
            "date": "2026-10-15",
            "start_time": "14:00",
            "end_time": "16:00",
            "orig_start_time": "14:00",
            "orig_end_time": "18:00",
        }
        slot_key = "RIG_1|2026-10-15|14:00|18:00"
        base_slider_key = slot_picker_table._stable_slider_key(slot_key)
        modal_slider_key = f"modal_{base_slider_key}"
        state = {
            "calendar_modal_open": False,
            "candidate_slots": [slot],
            base_slider_key: ("14:00", "16:00"),
            modal_slider_key: ("14:00", "16:00"),
        }
        with patch.object(st, "session_state", state):
            slot_picker_table._open_calendar_modal()
            self.assertTrue(state["calendar_modal_open"])
            slot_picker_table._resize_selected_slot(
                slot_key,
                modal_slider_key,
                30,
            )
            slot_picker_table._close_calendar_modal()

        self.assertFalse(state["calendar_modal_open"])
        self.assertEqual(slot["start_time"], "14:00")
        self.assertEqual(slot["end_time"], "16:30")
        self.assertEqual(slot["duration_hrs"], 2.5)
        self.assertEqual(state[base_slider_key], ("14:00", "16:30"))
        self.assertEqual(state[modal_slider_key], ("14:00", "16:30"))

    def test_calendar_modal_uses_distinct_booking_footer_container_keys(self) -> None:
        slot = {
            "rig_id": "RIG_1",
            "date": "2026-10-15",
            "start_time": "14:00",
            "end_time": "16:00",
            "orig_start_time": "14:00",
            "orig_end_time": "18:00",
        }
        state = SessionState(
            {
                "right_panel_view": "Weekly Calendars",
                "calendar_modal_open": True,
                "matched_rigs": [{"rig_id": "RIG_1", "platform": "Vector"}],
                "candidate_slots": [slot],
                "selected_slot_keys": ["RIG_1|2026-10-15|14:00|18:00"],
                "search_settings": {
                    "start_date": "2026-10-15",
                    "shift_start": "09:00",
                    "shift_end": "18:00",
                    "allow_weekends": False,
                    "include_extended": False,
                },
            }
        )
        rendered_container_keys = []

        def make_container(*args, **kwargs):
            rendered_container_keys.append(kwargs.get("key"))
            return MagicMock()

        with (
            patch.object(st, "session_state", state),
            patch.object(slot_picker_table, "_render_view_toggle"),
            patch.object(
                slot_picker_table,
                "_render_weekly_calendars",
            ) as render_weekly_calendars,
            patch.object(st, "container", side_effect=make_container),
            patch.object(st, "selectbox", return_value="-- Select Slot Type --"),
            patch.object(st, "button", return_value=False),
            patch.object(
                slot_picker_table,
                "_open_expanded_calendar_dialog",
                side_effect=lambda user_id: slot_picker_table._render_booking_footer(
                    user_id,
                    key_prefix="modal_",
                ),
            ),
        ):
            slot_picker_table.render_slot_picker("USER_ENG_01")

        self.assertIn("ciara_booking_cta", rendered_container_keys)
        self.assertIn("modal_ciara_booking_cta", rendered_container_keys)
        self.assertEqual(
            rendered_container_keys.count("ciara_booking_cta"),
            1,
        )
        self.assertEqual(
            rendered_container_keys.count("modal_ciara_booking_cta"),
            1,
        )
        self.assertFalse(state["calendar_modal_open"])
        render_weekly_calendars.assert_called_once_with(
            in_modal=False,
            modal_is_open=True,
        )


class ProductionDurationAndGatekeeperTests(unittest.TestCase):
    def test_minutes_are_converted_and_each_uses_custom_catalog_targets(self) -> None:
        state = {
            "_turn_match_targets": [
                "SCALEXIO_ADAS_01",
                "VT_BENCH_A",
            ]
        }
        with patch.object(st, "session_state", state):
            self.assertEqual(
                scheduling_tools._duration_explicitly_requested("90 minutes"),
                1.5,
            )
            self.assertEqual(
                scheduling_tools._duration_explicitly_requested(
                    "Test SCALEXIO_ADAS_01 and VT_BENCH_A for 4 hours each."
                ),
                8.0,
            )

    def test_for_each_preposition_and_vehicle_program_scope(self) -> None:
        state = {
            "_turn_match_targets": [
                "ECU1, ECU2 + VEHICLE_PROGRAM_1",
            ]
        }
        with patch.object(st, "session_state", state):
            self.assertEqual(
                scheduling_tools._duration_explicitly_requested(
                    "Test ECU1 and ECU2 on VEHICLE_PROGRAM_1 for 1 hour each."
                ),
                2.0,
            )
            self.assertEqual(
                scheduling_tools._duration_explicitly_requested(
                    "Test ECU1 and ECU2 for 1 hour for each ECU."
                ),
                2.0,
            )
            self.assertEqual(
                scheduling_tools._duration_explicitly_requested(
                    "Test ECU1 and ECU2 on VEHICLE_PROGRAM_1 "
                    "for 1 hour for each ECU."
                ),
                2.0,
            )

    def test_bms_vcu_each_ecu_excludes_scoped_program(self) -> None:
        categories = {
            "rig": set(),
            "feature": set(),
            "vehicle_program": {"VP_GEN3"},
            "ecu": {"BMS", "VCU"},
        }
        with (
            patch.object(st, "session_state", {"_turn_match_targets": []}),
            patch.object(
                scheduling_tools,
                "_known_target_categories",
                return_value=categories,
            ),
        ):
            self.assertEqual(
                scheduling_tools._duration_explicitly_requested(
                    "Test BMS and VCU on VP_GEN3 for 1 hour for each ECU."
                ),
                2.0,
            )
            self.assertEqual(
                scheduling_tools._duration_explicitly_requested(
                    "Test BMS and VCU on VP_GEN3 for 1 hour each."
                ),
                2.0,
            )

    def test_extended_shift_offset_is_not_a_booking_duration(self) -> None:
        prompt = (
            "I want to test FEATURE_1 for 3 hours, and I am okay with "
            "+-2 hours extended shift."
        )
        with patch.object(
            st,
            "session_state",
            {"_turn_match_targets": ["FEATURE_1"]},
        ):
            self.assertEqual(
                scheduling_tools._duration_explicitly_requested(prompt),
                3.0,
            )

    def test_extended_shift_offset_does_not_bypass_duration_gatekeeper(self) -> None:
        prompt = (
            "I want to test FEATURE_1 with +-2 hours extended shift."
        )
        with patch.object(
            st,
            "session_state",
            {"target_duration_hours": 0.0},
        ):
            self.assertTrue(
                orchestrator._needs_duration_gatekeeper(prompt, [])
            )

    def test_cable_m_does_not_count_as_duration(self) -> None:
        self.assertFalse(
            orchestrator._messages_contain_duration(
                "Test ECU21 using a 2m cable.", []
            )
        )
        self.assertTrue(
            orchestrator._messages_contain_duration(
                "Test ECU21 for 90 minutes.", []
            )
        )

    def test_old_booking_history_does_not_satisfy_new_turn_duration(self) -> None:
        state = {
            "target_duration_hours": 0.0,
            "last_booking_message_index": 2,
        }
        messages = [
            {"role": "user", "content": "Test FEATURE_1 for 2 hours."},
            {"role": "assistant", "content": "Booking complete."},
            {
                "role": "user",
                "content": "Now find a rig for FEATURE_2.",
            },
        ]
        with patch.object(st, "session_state", state):
            self.assertTrue(
                orchestrator._needs_duration_gatekeeper(
                    "Now find a rig for FEATURE_2.", messages
                )
            )

    def test_catalog_target_names_trigger_duration_gatekeeper(self) -> None:
        with (
            patch.object(st, "session_state", {"target_duration_hours": 0.0}),
            patch.object(
                orchestrator,
                "_known_target_identifiers",
                return_value={"ADAS_AEB", "VP_GEN3", "SCALEXIO_ADAS_01"},
            ),
        ):
            self.assertTrue(
                orchestrator._needs_duration_gatekeeper(
                    "I want to test ADAS_AEB on VP_GEN3.", []
                )
            )
            self.assertTrue(
                orchestrator._needs_duration_gatekeeper(
                    "Book SCALEXIO_ADAS_01.", []
                )
            )

    def test_successful_booking_resets_duration_and_adds_alternating_history(self) -> None:
        state = {
            "agent_history": [],
            "messages": [{"role": "user", "content": "Book RIG_1 for 2 hours."}],
            "target_duration_hours": 2.0,
        }
        with (
            patch.object(st, "session_state", state),
            patch.object(slot_picker_table, "LLM_PROVIDER", "gemini"),
        ):
            slot_picker_table._append_booking_history_notice(
                [
                    {
                        "rig_id": "RIG_1",
                        "date": "2026-10-21",
                        "start_time": "09:00",
                        "end_time": "11:00",
                    }
                ],
                ["BK_201"],
                "MANUAL_TESTING",
            )

        self.assertEqual(state["target_duration_hours"], 0.0)
        self.assertEqual(state["last_booking_message_index"], 2)
        self.assertEqual(
            [item.role for item in state["agent_history"]],
            ["user", "model"],
        )


class CompoundMatcherProductionTests(unittest.TestCase):
    @staticmethod
    def rig(
        rig_id: str,
        program: str,
        real_ecus: str,
    ) -> dict[str, str]:
        return {
            "Rig_ID": rig_id,
            "Vehicle_Program": program,
            "Rig_Platform": "Vector",
            "Rig_Domain": "ADAS",
            "Rig_Engineer": "ENG_1",
            "Real_Connected_Components": real_ecus,
            "CAN_Sim_ECUs": "",
            "Eth_Sim_ECUs": "",
        }

    @staticmethod
    def repository(
        rigs: list[dict[str, str]],
        feature_real_ecus: str = "ECU1|ECU2|ECU3",
        applicable_ecus: str = "ECU1|ECU2|ECU3",
    ) -> Mock:
        repository = Mock()
        repository.get_all_rigs.return_value = pd.DataFrame(rigs)
        repository.get_feature_requirements.return_value = pd.DataFrame(
            [
                {
                    "Feature_Name": "FEATURE_1",
                    "Vehicle_Program": "VEHICLE_PROGRAM_1",
                    "Real_ECUs_Required": feature_real_ecus,
                    "CAN_Sim_Needed": "",
                    "Eth_Sim_Needed": "",
                }
            ]
        )
        repository.get_vehicle_program_ecus.return_value = pd.DataFrame(
            [
                {
                    "Vehicle_Program": "VEHICLE_PROGRAM_1",
                    "Applicable_ECUs": applicable_ecus,
                }
            ]
        )
        return repository

    def test_ecu_query_with_compatible_program_uses_program_as_qualifier(self) -> None:
        repository = self.repository(
            [
                self.rig("RIG_1", "VEHICLE_PROGRAM_1", "ECU1|ECU2"),
                self.rig("RIG_2", "VEHICLE_PROGRAM_2", "ECU1|ECU2"),
            ]
        )

        result = CapabilityMatcherService(repository).match_rigs(
            ecus_requested=["ECU1", "ECU2"],
            vehicle_program="VEHICLE_PROGRAM_1",
        )

        self.assertEqual(
            list(result["request_groups"]),
            ["ECU1, ECU2"],
        )
        self.assertEqual(
            [rig["rig_id"] for rig in result["rigs"]],
            ["RIG_1", "RIG_2"],
        )

    def test_zero_padded_direct_rig_keeps_its_partial_feature_score(self) -> None:
        repository = self.repository(
            [
                self.rig("RIG_1", "VEHICLE_PROGRAM_1", "ECU1|ECU2|ECU3"),
                self.rig("RIG_3", "VEHICLE_PROGRAM_1", "ECU1|ECU2"),
            ]
        )

        result = CapabilityMatcherService(repository).match_rigs(
            rig_id="RIG_03",
            feature_name="FEATURE_1",
        )

        rig_three = next(rig for rig in result["rigs"] if rig["rig_id"] == "RIG_3")
        self.assertEqual(rig_three["match_score"], 66.7)
        self.assertEqual(rig_three["matched_for"], "FEATURE_1")
        self.assertEqual(rig_three["missing"], ["ECU3 (Real missing)"])
        self.assertNotIn("RIG_3", result["request_groups"])
        self.assertNotIn("RIG_3", result["request_groups"].get("RIG_03", []))

    def test_unsupported_direct_rig_is_a_clean_separate_booking_target(self) -> None:
        repository = self.repository(
            [
                self.rig("RIG_1", "VEHICLE_PROGRAM_1", "ECU1|ECU2|ECU3"),
                self.rig("RIG_10", "VEHICLE_PROGRAM_4", "ECU12"),
            ]
        )

        result = CapabilityMatcherService(repository).match_rigs(
            rig_id="RIG_10",
            feature_name="FEATURE_1",
            vehicle_program="VEHICLE_PROGRAM_1",
        )

        direct = next(rig for rig in result["rigs"] if rig["rig_id"] == "RIG_10")
        self.assertEqual(direct["match_score"], 100.0)
        self.assertEqual(direct["matched_for"], "RIG_10")
        self.assertEqual(direct["missing"], [])
        self.assertEqual(direct["downgrades"], [])
        self.assertEqual(direct["ecu_breakdown"], [])
        self.assertNotIn("RIG_10", result["request_groups"]["FEATURE_1"])


class DiscoveryAndSlotStagingRegressionTests(unittest.TestCase):
    def test_post_turn_fallback_stages_matched_rigs_with_explicit_duration(self) -> None:
        state = SessionState(
            {
                "_turn_matched_rigs_by_id": {
                    "RIG_1": {"rig_id": "RIG_1"},
                    "RIG_2": {"rig_id": "RIG_2"},
                },
                "_turn_candidate_slots": [],
                "target_duration_hours": 0.0,
            }
        )
        with (
            patch.object(st, "session_state", state),
            patch.object(
                orchestrator,
                "_duration_explicitly_requested",
                return_value=3.0,
            ),
            patch.object(orchestrator, "find_available_slots") as stage_slots,
        ):
            orchestrator._ensure_turn_slots_staged(
                "Test FEATURE_1 for 3 hours."
            )

        stage_slots.assert_called_once_with(
            rig_ids=["RIG_1", "RIG_2"],
            duration_hours=3.0,
        )

    def test_post_turn_fallback_skips_when_candidate_slots_are_staged(self) -> None:
        state = SessionState(
            {
                "_turn_matched_rigs_by_id": {"RIG_1": {"rig_id": "RIG_1"}},
                "_turn_candidate_slots": [{"rig_id": "RIG_1"}],
                "target_duration_hours": 3.0,
            }
        )
        with (
            patch.object(st, "session_state", state),
            patch.object(orchestrator, "find_available_slots") as stage_slots,
        ):
            orchestrator._ensure_turn_slots_staged("Test FEATURE_1.")

        stage_slots.assert_not_called()

    def test_matcher_payload_drops_cross_program_ecu_noise_for_same_program_top3(
        self,
    ) -> None:
        rig_ids = ["RIG_1", "RIG_2", "RIG_3"]
        result = {
            "rigs": [
                {
                    "rig_id": rig_id,
                    "match_score": 100.0,
                    "is_cross_program": False,
                }
                for rig_id in rig_ids
            ],
            "request_groups": {"FEATURE_1": rig_ids},
            "cross_program_ecus": [{"rig_id": f"RIG_{index}"} for index in range(5)],
        }
        state = SessionState(
            {"_turn_matched_rigs_by_id": {}, "matched_rigs": []}
        )
        service = Mock()
        service.match_rigs.return_value = result
        with (
            patch.object(st, "session_state", state),
            patch.object(
                discovery_tools,
                "CapabilityMatcherService",
                return_value=service,
            ),
            patch.object(discovery_tools, "get_repository"),
        ):
            payload = discovery_tools.match_rigs_by_criteria(
                feature_name="FEATURE_1"
            )

        self.assertNotIn("cross_program_ecus", payload)

    def test_can_simulation_exact_match_is_not_discrepant(self) -> None:
        from src.agent.tools.discovery_tools import _ecu_breakdown_is_discrepant

        self.assertFalse(
            _ecu_breakdown_is_discrepant(
                {"required": "CAN_Sim", "available": "CAN simulation"}
            )
        )
        self.assertTrue(
            _ecu_breakdown_is_discrepant(
                {"required": "CAN_Sim", "available": "Missing"}
            )
        )

    def test_find_available_slots_records_pre_merge_ids_and_clears_widget(self) -> None:
        state = SessionState(
            {
                "_turn_match_targets": ["FEATURE_1", "FEATURE_2"],
                "_turn_matched_rigs_by_id": {
                    "RIG_1": {"rig_id": "RIG_1"},
                    "RIG_2": {"rig_id": "RIG_2"},
                },
                "_turn_last_batch_rig_ids": ["RIG_2"],
                "_turn_candidate_slots": [],
                "_turn_slot_durations": [],
                "_turn_user_message": "Test features.",
                "candidate_slots": [],
                "candidate_slot_editor": {"edited_rows": [0]},
                "messages": [],
                "search_settings": {},
            }
        )
        repository = Mock()
        repository.get_all_rigs.return_value = pd.DataFrame(
            {"Rig_ID": ["RIG_1", "RIG_2"]}
        )
        scheduler = Mock()
        scheduler.find_free_slots.return_value = {
            "standard_slots": [],
            "extended_slots": [],
        }
        with (
            patch.object(st, "session_state", state),
            patch.object(scheduling_tools, "get_repository", return_value=repository),
            patch.object(scheduling_tools, "SlotSchedulerService", return_value=scheduler),
        ):
            scheduling_tools.find_available_slots(["RIG_01"], 2.0)

        self.assertEqual(state["_turn_slot_durations"], [(("RIG_1",), 2.0)])
        self.assertEqual(
            scheduler.find_free_slots.call_args.kwargs["rig_ids"],
            ["RIG_1", "RIG_2"],
        )
        self.assertNotIn("candidate_slot_editor", state)

    def test_find_available_slots_replaces_parallel_guessed_ids_with_turn_matched_ids(
        self,
    ) -> None:
        rig_ids = ["RIG_15", "RIG_21", "RIG_28", "RIG_18", "RIG_24", "RIG_30"]
        state = SessionState(
            {
                "_turn_match_targets": ["FEATURE_7", "FEATURE_8"],
                "_turn_matched_rigs_by_id": {
                    rig_id: {
                        "rig_id": rig_id,
                        "matched_for": "FEATURE_7 or FEATURE_8",
                        "match_score": 100.0,
                    }
                    for rig_id in rig_ids
                },
                "_turn_last_batch_rig_ids": [],
                "_turn_direct_rig_ids": [],
                "_turn_candidate_slots": [],
                "_turn_slot_durations": [],
                "_turn_user_message": (
                    "I want to test FEATURE_7 and FEATURE_8 for 4 hours each."
                ),
                "candidate_slots": [],
                "messages": [],
                "search_settings": {},
            }
        )
        repository = Mock()
        repository.get_all_rigs.return_value = pd.DataFrame(
            {"Rig_ID": rig_ids}
        )
        scheduler = Mock()
        scheduler.find_free_slots.return_value = {
            "standard_slots": [
                {
                    "rig_id": rig_id,
                    "date": "2026-10-15",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "window_type": "standard",
                }
                for rig_id in rig_ids
            ],
            "extended_slots": [],
        }

        with (
            patch.object(st, "session_state", state),
            patch.object(
                scheduling_tools, "get_repository", return_value=repository
            ),
            patch.object(
                scheduling_tools,
                "SlotSchedulerService",
                return_value=scheduler,
            ),
        ):
            scheduling_tools.find_available_slots(
                ["RIG_01", "RIG_02", "Rig_A1"],
                4.0,
            )

        self.assertEqual(
            scheduler.find_free_slots.call_args.kwargs["rig_ids"],
            rig_ids,
        )
        self.assertEqual(
            [slot["rig_id"] for slot in state["candidate_slots"]],
            rig_ids,
        )
        self.assertEqual(
            state["_turn_slot_durations"],
            [(tuple(rig_ids), 4.0)],
        )

    def test_stage_filtered_slots_clears_stale_widget_state(self) -> None:
        state = SessionState(
            {
                "slot_search_context": {},
                "search_settings": {},
                "matched_rigs": [],
                "candidate_slot_editor": {"edited_rows": [0]},
            }
        )
        repository = Mock()
        repository.get_all_rigs.return_value = pd.DataFrame({"Rig_ID": ["RIG_1"]})
        scheduler = Mock()
        scheduler.find_free_slots.return_value = {
            "standard_slots": [],
            "extended_slots": [],
        }
        with (
            patch.object(st, "session_state", state),
            patch.object(scheduling_tools, "get_repository", return_value=repository),
            patch.object(scheduling_tools, "SlotSchedulerService", return_value=scheduler),
        ):
            scheduling_tools.stage_filtered_slots_for_ui(["RIG_1"], 1.0)

        self.assertNotIn("candidate_slot_editor", state)


class RepositoryProductionTests(unittest.TestCase):
    def test_repository_factory_selects_configured_source(self) -> None:
        with patch.dict(os.environ, {"HIL_DATA_SOURCE": "csv"}):
            self.assertIsInstance(get_repository(), CSVHILRepository)
        with (
            patch.dict(os.environ, {"HIL_DATA_SOURCE": "ciara_api"}),
            patch("src.repositories.CiaraAPIRepository") as api_repository,
        ):
            get_repository()
            api_repository.assert_called_once_with()

    def test_csv_reads_are_cached_by_mtime_and_return_independent_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            data_dir = Path(temp_directory)
            rigs_path = data_dir / "rig_capabilities.csv"
            pd.DataFrame({"Rig_ID": ["RIG_1"]}).to_csv(rigs_path, index=False)
            repository = CSVHILRepository(data_dir)
            original_read_csv = pd.read_csv
            with patch(
                "src.repositories.csv_repository.pd.read_csv",
                wraps=original_read_csv,
            ) as read_csv:
                first = repository.get_all_rigs()
                first.loc[0, "Rig_ID"] = "MUTATED"
                second = repository.get_all_rigs()
                self.assertEqual(second.loc[0, "Rig_ID"], "RIG_1")
                self.assertEqual(read_csv.call_count, 1)

                stat = rigs_path.stat()
                os.utime(
                    rigs_path,
                    ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000),
                )
                repository.get_all_rigs()
                self.assertEqual(read_csv.call_count, 2)

    def test_concurrent_booking_appends_are_atomic_and_keep_unique_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            data_dir = Path(temp_directory)
            bookings_path = data_dir / "ciara_bookings.csv"
            pd.DataFrame(
                columns=[
                    "Booking_ID",
                    "Rig_ID",
                    "Date",
                    "Slot_Start_Time",
                    "Slot_End_Time",
                    "Slot_Type",
                    "Booked_By_User",
                ]
            ).to_csv(bookings_path, index=False)

            def append_one(index: int) -> list[str]:
                return CSVHILRepository(data_dir).append_bookings(
                    [
                        {
                            "Rig_ID": f"RIG_{index}",
                            "Date": "2026-10-21",
                            "Slot_Start_Time": "09:00",
                            "Slot_End_Time": "10:00",
                            "Slot_Type": "MANUAL_TESTING",
                            "Booked_By_User": f"ENG_{index}",
                        }
                    ]
                )

            with ThreadPoolExecutor(max_workers=8) as executor:
                booking_ids = [
                    booking_id
                    for batch in executor.map(append_one, range(1, 9))
                    for booking_id in batch
                ]
            persisted = pd.read_csv(bookings_path, dtype=str)
            self.assertEqual(len(persisted), 8)
            self.assertEqual(len(set(booking_ids)), 8)
            self.assertEqual(set(persisted["Booking_ID"]), set(booking_ids))
            self.assertFalse(list(data_dir.glob(".ciara_bookings.csv.*.tmp")))


if __name__ == "__main__":
    unittest.main()
