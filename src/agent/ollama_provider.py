"""Ollama chat provider with explicit local tool execution."""

import inspect
import json
import re
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from src.agent.tools.registry import get_registered_tools
from src.config.settings import (
    OLLAMA_BASE_URL,
    OLLAMA_MAX_TOOL_ROUNDS,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_TIMEOUT_SECONDS,
)
from src.utils.benchmarking import mark_benchmark
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class OllamaProvider:
    """Send chat turns to Ollama and execute its registered tool calls."""

    def __init__(self, system_instruction: str) -> None:
        self.system_instruction = system_instruction

    def respond(
        self,
        user_message: str,
        history: list[dict[str, Any]],
        benchmark: Any = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Return a model response and the updated provider-specific history."""
        messages = [*history, {"role": "user", "content": user_message}]
        tools = get_registered_tools()
        tools_by_name = {tool.__name__: tool for tool in tools}
        tool_schemas = [_tool_schema(tool) for tool in tools]
        tool_rounds = 0

        while True:
            request_messages = [
                {"role": "system", "content": self.system_instruction},
                *messages,
            ]
            mark_benchmark(
                benchmark,
                "ollama_chat_request_started",
                model=OLLAMA_MODEL,
                tool_round=tool_rounds,
                history_items=len(messages),
            )
            started_ns = time.perf_counter_ns()
            response = self._send_chat(request_messages, tool_schemas, benchmark)
            request_elapsed_us = (time.perf_counter_ns() - started_ns) // 1_000
            assistant_message = response.get("message")
            if not isinstance(assistant_message, dict):
                raise RuntimeError("Ollama returned a response without a message.")
            messages.append(assistant_message)
            mark_benchmark(
                benchmark,
                "ollama_chat_response_received",
                model=OLLAMA_MODEL,
                tool_round=tool_rounds,
                request_elapsed_us=request_elapsed_us,
            )

            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                answer = assistant_message.get("content")
                if not isinstance(answer, str) or not answer.strip():
                    raise RuntimeError("Ollama returned an empty response.")
                return answer, messages

            if tool_rounds >= OLLAMA_MAX_TOOL_ROUNDS:
                raise RuntimeError(
                    "Ollama exceeded the configured limit of "
                    f"{OLLAMA_MAX_TOOL_ROUNDS} tool-calling rounds."
                )
            tool_rounds += 1
            for call in tool_calls:
                tool_call = call.get("function", {})
                tool_name = tool_call.get("name")
                tool = tools_by_name.get(tool_name)
                if tool is None:
                    raise RuntimeError(
                        f"Ollama requested an unregistered tool: {tool_name!r}."
                    )
                arguments = _parse_tool_arguments(tool_call.get("arguments"))
                try:
                    inspect.signature(tool).bind(**arguments)
                except TypeError as exc:
                    raise RuntimeError(
                        f"Ollama returned invalid arguments for tool {tool_name!r}: {exc}"
                    ) from exc
                mark_benchmark(
                    benchmark,
                    "ollama_tool_call_received",
                    tool=tool_name,
                    tool_round=tool_rounds,
                )
                result = tool(**arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": tool_name,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

    def _send_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        benchmark: Any = None,
    ) -> dict[str, Any]:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "think": False,
            "options": {"num_ctx": OLLAMA_NUM_CTX},
        }
        request = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=OLLAMA_TIMEOUT_SECONDS,
            ) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            logger.error(
                "Ollama chat request failed: status=%d body=%s",
                exc.code,
                body[:1000],
            )
            mark_benchmark(
                benchmark,
                "ollama_chat_request_failed",
                status_code=exc.code,
            )
            raise RuntimeError(
                f"Ollama returned HTTP {exc.code}: {body[:1000]}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            logger.exception(
                "Unable to complete Ollama chat request: endpoint=%s model=%s",
                OLLAMA_BASE_URL,
                OLLAMA_MODEL,
            )
            mark_benchmark(
                benchmark,
                "ollama_chat_request_failed",
                exception_type=type(exc).__name__,
            )
            raise RuntimeError(
                f"Unable to reach Ollama at {OLLAMA_BASE_URL}: {exc}"
            ) from exc
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            logger.exception("Ollama returned invalid JSON from /api/chat.")
            raise RuntimeError("Ollama returned an invalid chat response.") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("Ollama returned an invalid chat response object.")
        return parsed


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Ollama returned invalid JSON tool arguments.") from exc
    if not isinstance(arguments, dict):
        raise RuntimeError("Ollama tool arguments must be a JSON object.")
    return arguments


def _tool_schema(tool: Callable[..., Any]) -> dict[str, Any]:
    signature = inspect.signature(tool)
    type_hints = get_type_hints(tool)
    descriptions = _parameter_descriptions(inspect.getdoc(tool) or "")
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter in signature.parameters.items():
        annotation = type_hints.get(name, parameter.annotation)
        properties[name] = _json_schema_type(annotation)
        if name in descriptions:
            properties[name]["description"] = descriptions[name]
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
    docstring = inspect.getdoc(tool) or ""
    description = re.split(r"\n\s*(?:Args|Parameters|Returns):", docstring, maxsplit=1)[0]
    return {
        "type": "function",
        "function": {
            "name": tool.__name__,
            "description": description.strip(),
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def _json_schema_type(annotation: Any) -> dict[str, Any]:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in {Union, UnionType}:
        annotation = next((arg for arg in args if arg is not type(None)), Any)
        origin = get_origin(annotation)
        args = get_args(annotation)
    if annotation is str:
        return {"type": "string"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if origin is list:
        item_type = args[0] if args else Any
        return {"type": "array", "items": _json_schema_type(item_type)}
    if origin is dict:
        value_type = args[1] if len(args) > 1 else Any
        return {"type": "object", "additionalProperties": _json_schema_type(value_type)}
    return {"type": "object"}


def _parameter_descriptions(docstring: str) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    in_args = False
    for line in inspect.cleandoc(docstring).splitlines():
        if line.strip() in {"Args:", "Parameters:"}:
            in_args = True
            continue
        if in_args and line.strip() in {"Returns:", "Raises:"}:
            break
        if in_args:
            match = re.match(r"\s+(\w+):\s*(.*)", line)
            if match:
                descriptions[match.group(1)] = match.group(2).strip()
    return descriptions
