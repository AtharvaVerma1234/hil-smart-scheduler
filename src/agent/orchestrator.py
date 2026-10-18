"""LLM provider coordinator for HIL discovery and scheduling."""

from pathlib import Path
from typing import Any

import streamlit as st
from google import genai
from google.genai import types

from src.agent.ollama_provider import OllamaProvider
from src.agent.tools.registry import get_registered_tools
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
        if self.provider == "ollama":
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
                tool_count=len(get_registered_tools()),
                history_items=len(history),
            )
            try:
                response, updated_history = OllamaProvider(
                    self.system_instruction
                ).respond(user_message, history, benchmark)
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
            tools=get_registered_tools(),
            system_instruction=self.system_instruction,
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
            response = chat.send_message(user_message)
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
        if not response.text:
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
            len(response.text),
            len(st.session_state.agent_history),
            len(st.session_state.get("tool_trace", [])) - trace_count_before,
        )
        return response.text


def tool_trace_summary() -> list[dict[str, Any]]:
    """Return the latest tool trace entries for UI display."""
    return list(st.session_state.get("tool_trace", []))
