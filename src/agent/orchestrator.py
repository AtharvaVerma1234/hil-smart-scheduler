"""LLM provider coordinator for HIL discovery and scheduling."""

from pathlib import Path
import re
from typing import Any

import streamlit as st
from google import genai
from google.genai import types

from src.agent.ollama_provider import OllamaProvider
from src.agent.tools.registry import get_registered_tools
from src.agent.tools.scheduling_tools import (
    _duration_explicitly_requested,
    _known_target_identifiers,
    find_available_slots,
    find_booking_duration_matches,
)
from src.config.settings import (
    ACTIVE_MODEL,
    GEMINI_API_KEY,
    GEMINI_THINKING_BUDGET,
    LLM_PROVIDER,
)
from src.utils.benchmarking import mark_benchmark
from src.utils.logging_config import get_logger

SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "system_coordinator.md"
logger = get_logger(__name__)

_DISCOVERY_INTENT_RE = re.compile(
    r"\b(?:test(?:ing)?|book(?:ing)?|find|search|schedule|reserve|suggest|recommend)\b",
    re.IGNORECASE,
)
_DISCOVERY_TARGET_RE = re.compile(
    r"\b(?:rig|feature|ecu|vehicle\s+program)\b|"
    r"\b(?:RIG|FEATURE|ECU|VEHICLE_PROGRAM)_?[A-Z0-9]+\b",
    re.IGNORECASE,
)
_DURATION_GATEKEEPER_NOTE = (
    "System note: The user is asking about rig/feature discovery but has not "
    "provided a test duration. Ask ONLY for the missing test duration in hours. "
    "Do not ask for Slot_Type or call discovery or scheduling tools."
)


def _reset_turn_accumulators(user_message: str = "") -> None:
    st.session_state["_turn_matched_rigs_by_id"] = {}
    st.session_state["_turn_last_batch_rig_ids"] = []
    st.session_state["_turn_candidate_slots"] = []
    st.session_state["_turn_slot_durations"] = []
    st.session_state["_turn_match_targets"] = []
    st.session_state["_turn_direct_rig_ids"] = []
    st.session_state["_turn_user_message"] = user_message


def _ensure_turn_slots_staged(user_message: str) -> None:
    """Auto-stage slots if the LLM matched rigs but skipped availability search."""
    matched_by_id = st.session_state.get("_turn_matched_rigs_by_id") or {}
    if not matched_by_id or st.session_state.get("_turn_candidate_slots"):
        return
    duration = _duration_explicitly_requested(user_message) or float(
        st.session_state.get("target_duration_hours", 0.0)
    )
    if duration > 0:
        find_available_slots(
            rig_ids=list(matched_by_id),
            duration_hours=float(duration),
        )


def _active_user_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    start_index = st.session_state.get("last_booking_message_index", 0)
    if not isinstance(start_index, int) or start_index < 0:
        start_index = 0
    return [
        message
        for message in messages[start_index:]
        if message.get("role") == "user"
    ]


def _messages_contain_duration(
    user_message: str, messages: list[dict[str, Any]]
) -> bool:
    recent_users = _active_user_messages(messages)
    user_text = "\n".join(
        [str(message.get("content", "")) for message in recent_users]
        + (
            []
            if recent_users and str(recent_users[-1].get("content", "")) == user_message
            else [user_message]
        )
    )
    return bool(find_booking_duration_matches(user_text))


def _needs_duration_gatekeeper(user_message: str, messages: list[dict[str, Any]]) -> bool:
    recent_users = _active_user_messages(messages)
    conversation_text = "\n".join(
        [str(message.get("content", "")) for message in recent_users]
        + (
            []
            if recent_users and str(recent_users[-1].get("content", "")) == user_message
            else [user_message]
        )
    )
    target_duration = st.session_state.get("target_duration_hours", 0)
    has_session_duration = (
        isinstance(target_duration, (int, float))
        and not isinstance(target_duration, bool)
        and target_duration > 0
    )
    asks_for_discovery = bool(
        _DISCOVERY_INTENT_RE.search(conversation_text)
        and _contains_discovery_target(conversation_text)
    )
    return asks_for_discovery and not (
        has_session_duration or _messages_contain_duration(user_message, messages)
    )


def _contains_discovery_target(text: str) -> bool:
    if _DISCOVERY_TARGET_RE.search(text) or re.search(
        r"\b(?:bench|testbench|dspace|vector|ni)\b",
        text,
        re.IGNORECASE,
    ):
        return True
    return any(
        re.search(
            rf"(?<![A-Z0-9]){re.escape(identifier)}(?![A-Z0-9])",
            text,
            re.IGNORECASE,
        )
        for identifier in _known_target_identifiers()
        if identifier
    )


class AgentOrchestrator:
    """Route chat turns to the configured provider and deterministic tools."""

    def __init__(self, api_key: str = "") -> None:
        benchmark = st.session_state.get("benchmark_trace")
        self.provider = LLM_PROVIDER
        self.model = ACTIVE_MODEL
        self.client: genai.Client | None = None
        if self.provider == "gemini" and not (api_key or GEMINI_API_KEY).strip():
            mark_benchmark(
                benchmark,
                "agent_initialization_failed",
                reason="missing_api_key",
            )
            logger.error(
                "Agent initialization rejected: Gemini API key is not configured."
            )
            raise ValueError("Gemini API key is required to use the chat assistant.")
        if self.provider == "gemini":
            mark_benchmark(benchmark, "gemini_client_initialization_started")
            try:
                self.client = genai.Client(api_key=(api_key or GEMINI_API_KEY).strip())
            except Exception as exc:
                mark_benchmark(
                    benchmark,
                    "gemini_client_initialization_failed",
                    exception_type=type(exc).__name__,
                )
                logger.exception(
                    "Failed to initialize Gemini client; API key value was not logged."
                )
                raise
            mark_benchmark(benchmark, "gemini_client_initialized")
        else:
            mark_benchmark(
                benchmark,
                "ollama_provider_initialized",
                model=self.model,
            )
        mark_benchmark(benchmark, "coordinator_prompt_load_started")
        try:
            self.system_instruction = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            mark_benchmark(
                benchmark,
                "coordinator_prompt_load_failed",
                exception_type=type(exc).__name__,
            )
            logger.exception("Failed to load coordinator prompt: path=%s", SYSTEM_PROMPT_PATH)
            raise
        mark_benchmark(
            benchmark,
            "coordinator_prompt_loaded",
            prompt_characters=len(self.system_instruction),
        )
        logger.info(
            "Agent initialized: provider=%s model=%s tool_count=%d prompt_path=%s",
            self.provider,
            self.model,
            len(get_registered_tools()),
            SYSTEM_PROMPT_PATH,
        )

    def respond(self, user_message: str) -> str:
        """Process one user turn while retaining the active provider's history."""
        benchmark = st.session_state.get("benchmark_trace")
        trace_count_before = len(st.session_state.get("tool_trace", []))
        gatekeeper_active = _needs_duration_gatekeeper(
            user_message, st.session_state.get("messages", [])
        )
        available_tools = [] if gatekeeper_active else get_registered_tools()
        request_instruction = self.system_instruction
        if gatekeeper_active:
            request_instruction = (
                f"{self.system_instruction}\n\n{_DURATION_GATEKEEPER_NOTE}"
            )
            mark_benchmark(
                benchmark,
                "duration_gatekeeper_activated",
                tool_count=0,
            )
            logger.info(
                "Duration gatekeeper activated: discovery tools disabled; "
                "message_characters=%d",
                len(user_message),
            )
        if self.provider == "ollama":
            _reset_turn_accumulators(user_message)
            history = st.session_state.get("ollama_history", [])
            logger.info(
                "Agent turn started: provider=%s model=%s message_characters=%d "
                "history_items=%d",
                self.provider,
                self.model,
                len(user_message),
                len(history),
            )
            mark_benchmark(
                benchmark,
                "ollama_request_configured",
                model=self.model,
                tool_count=len(available_tools),
                history_items=len(history),
            )
            try:
                response, updated_history = OllamaProvider(
                    request_instruction
                ).respond(
                    user_message,
                    history,
                    benchmark,
                    tools=available_tools,
                )
            except Exception as exc:
                mark_benchmark(
                    benchmark,
                    "ollama_agent_request_failed",
                    exception_type=type(exc).__name__,
                )
                logger.exception(
                    "Ollama request failed: model=%s history_items=%d "
                    "message_characters=%d",
                    self.model,
                    len(history),
                    len(user_message),
                )
                raise
            _ensure_turn_slots_staged(user_message)
            st.session_state.ollama_history = updated_history
            mark_benchmark(
                benchmark,
                "ollama_history_saved",
                history_items=len(updated_history),
            )
            logger.info(
                "Agent turn completed: provider=%s response_characters=%d "
                "history_items=%d tools_called=%d",
                self.provider,
                len(response),
                len(updated_history),
                len(st.session_state.get("tool_trace", [])) - trace_count_before,
            )
            return response

        history = st.session_state.get("agent_history", [])
        logger.info(
            "Agent turn started: provider=%s model=%s message_characters=%d "
            "history_items=%d",
            self.provider,
            self.model,
            len(user_message),
            len(history),
        )
        config_options: dict[str, Any] = {}
        if GEMINI_THINKING_BUDGET is not None:
            config_options["thinking_config"] = types.ThinkingConfig(
                thinking_budget=GEMINI_THINKING_BUDGET
            )
        config = types.GenerateContentConfig(
            tools=available_tools,
            system_instruction=request_instruction,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=False
            ),
            **config_options,
        )
        mark_benchmark(
            benchmark,
            "gemini_request_configured",
            model=self.model,
            tool_count=len(get_registered_tools()),
            history_items=len(history),
        )
        try:
            if self.client is None:
                raise RuntimeError("Gemini client was not initialized.")
            mark_benchmark(benchmark, "gemini_chat_creation_started")
            chat = self.client.chats.create(
                model=self.model,
                config=config,
                history=history,
            )
            mark_benchmark(benchmark, "gemini_chat_created")
            mark_benchmark(
                benchmark,
                "gemini_send_message_started",
                message_characters=len(user_message),
            )
            _reset_turn_accumulators(user_message)
            response = chat.send_message(user_message)
            _ensure_turn_slots_staged(user_message)
        except Exception as exc:
            mark_benchmark(
                benchmark,
                "gemini_request_failed",
                exception_type=type(exc).__name__,
                status_code=getattr(exc, "code", getattr(exc, "status_code", None)),
            )
            logger.exception(
                "Gemini request failed: model=%s history_items=%d message_characters=%d",
                self.model,
                len(history),
                len(user_message),
            )
            raise
        mark_benchmark(
            benchmark,
            "gemini_response_received",
            response_characters=len(response.text or ""),
        )
        response_text = (response.text or "").strip()
        if not response_text:
            matched = st.session_state.get("matched_rigs", [])
            if not matched:
                turn_matches = st.session_state.get(
                    "_turn_matched_rigs_by_id", {}
                )
                matched = (
                    list(turn_matches.values())
                    if isinstance(turn_matches, dict)
                    else list(turn_matches)
                )
            slots = st.session_state.get("candidate_slots", [])
            if matched or slots:
                rig_list = ", ".join(
                    str(rig.get("rig_id", rig.get("Rig_ID", "")))
                    for rig in matched
                )
                response_text = (
                    f"Found {len(matched)} compatible rig(s)"
                    f"{f' ({rig_list})' if rig_list else ''} and staged "
                    f"{len(slots)} available time slot(s) in the selector and right panel."
                )
                logger.warning(
                    "Gemini returned an empty response after staging results: "
                    "matched_rigs=%d candidate_slots=%d model=%s",
                    len(matched),
                    len(slots),
                    self.model,
                )
            else:
                mark_benchmark(benchmark, "gemini_response_empty")
                logger.error("Gemini returned an empty response: model=%s", self.model)
                raise RuntimeError("Gemini returned an empty response.")
        mark_benchmark(benchmark, "gemini_history_retrieval_started")
        st.session_state.agent_history = chat.get_history()
        mark_benchmark(
            benchmark,
            "gemini_history_saved",
            history_items=len(st.session_state.agent_history),
        )
        logger.info(
            "Agent turn completed: response_characters=%d history_items=%d "
            "tools_called=%d",
            len(response_text),
            len(st.session_state.agent_history),
            len(st.session_state.get("tool_trace", [])) - trace_count_before,
        )
        return response_text


def tool_trace_summary() -> list[dict[str, Any]]:
    """Return the latest tool trace entries for UI display."""
    return list(st.session_state.get("tool_trace", []))
