"""Tests for tool discipline guards and booking context synchronization."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import streamlit as st
from google.genai import types

from src.agent import orchestrator
from src.agent.tools import scheduling_tools
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
            patch.object(scheduling_tools, "CSVHILRepository"),
        ):
            scheduling_tools.find_available_slots(
                rig_ids=["RIG_2", "RIG_2"],
                duration_hours=4,
            )

        self.assertEqual(
            scheduler.find_free_slots.call_args.kwargs["rig_ids"],
            ["RIG_2", "RIG_1", "RIG_3"],
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
            patch.object(scheduling_tools, "CSVHILRepository"),
        ):
            scheduling_tools.find_available_slots(
                rig_ids=["RIG_OTHER"],
                duration_hours=4,
            )

        self.assertEqual(
            scheduler.find_free_slots.call_args.kwargs["rig_ids"],
            ["RIG_OTHER"],
        )


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

        self.assertEqual(len(state["agent_history"]), 1)
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


class GeminiThinkingBudgetTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
