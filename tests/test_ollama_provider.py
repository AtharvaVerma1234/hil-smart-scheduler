"""Focused tests for the Ollama tool-calling integration."""

import unittest
from unittest.mock import patch

from src.agent.ollama_provider import OllamaProvider, _tool_schema


def sample_tool(value: str, tags: list[str] | None = None) -> dict:
    """Return a test result.

    Args:
        value: Required lookup value.
        tags: Optional tags to apply.
    """
    return {"value": value, "tags": tags or []}


class OllamaProviderTests(unittest.TestCase):
    def test_tool_schema_includes_types_required_fields_and_descriptions(self) -> None:
        schema = _tool_schema(sample_tool)["function"]

        self.assertEqual(schema["name"], "sample_tool")
        self.assertEqual(
            schema["parameters"]["required"],
            ["value"],
        )
        self.assertFalse(schema["parameters"]["additionalProperties"])
        self.assertEqual(
            schema["parameters"]["properties"]["value"],
            {"type": "string", "description": "Required lookup value."},
        )
        self.assertEqual(
            schema["parameters"]["properties"]["tags"],
            {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags to apply.",
            },
        )

    def test_respond_executes_tool_and_continues_until_final_text(self) -> None:
        first_response = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "sample_tool",
                            "arguments": {"value": "rig-1", "tags": ["available"]},
                        }
                    }
                ],
            }
        }
        final_response = {
            "message": {"role": "assistant", "content": "The rig is available."}
        }
        provider = OllamaProvider("System instructions")
        with (
            patch(
                "src.agent.ollama_provider.get_registered_tools",
                return_value=[sample_tool],
            ),
            patch.object(
                provider,
                "_send_chat",
                side_effect=[first_response, final_response],
            ) as send_chat,
        ):
            answer, history = provider.respond("Find rig-1", [])

        self.assertEqual(answer, "The rig is available.")
        self.assertEqual(history[0], {"role": "user", "content": "Find rig-1"})
        self.assertEqual(history[1], first_response["message"])
        self.assertEqual(
            history[2],
            {
                "role": "tool",
                "tool_name": "sample_tool",
                "content": '{"value": "rig-1", "tags": ["available"]}',
            },
        )
        self.assertEqual(history[3], final_response["message"])
        self.assertEqual(send_chat.call_count, 2)
        self.assertEqual(
            send_chat.call_args_list[0].args[0][0],
            {"role": "system", "content": "System instructions"},
        )

    def test_respond_rejects_unregistered_tools(self) -> None:
        provider = OllamaProvider("System instructions")
        response = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "not_registered", "arguments": {}}}
                ],
            }
        }
        with (
            patch("src.agent.ollama_provider.get_registered_tools", return_value=[]),
            patch.object(provider, "_send_chat", return_value=response),
            self.assertRaisesRegex(RuntimeError, "unregistered tool"),
        ):
            provider.respond("Do something", [])

    def test_respond_rejects_arguments_not_supported_by_tool(self) -> None:
        provider = OllamaProvider("System instructions")
        response = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "sample_tool",
                            "arguments": {"value": "rig-1", "duration_hours": 2},
                        }
                    }
                ],
            }
        }
        with (
            patch(
                "src.agent.ollama_provider.get_registered_tools",
                return_value=[sample_tool],
            ),
            patch.object(provider, "_send_chat", return_value=response),
            self.assertRaisesRegex(RuntimeError, "invalid arguments"),
        ):
            provider.respond("Do something", [])

    def test_respond_can_disable_tool_calling_for_a_turn(self) -> None:
        provider = OllamaProvider("Ask for the duration.")
        final_response = {
            "message": {"role": "assistant", "content": "How many hours?"},
        }
        with (
            patch(
                "src.agent.ollama_provider.get_registered_tools",
                return_value=[sample_tool],
            ),
            patch.object(
                provider, "_send_chat", return_value=final_response
            ) as send_chat,
        ):
            answer, _ = provider.respond("Find a rig", [], tools=[])

        self.assertEqual(answer, "How many hours?")
        self.assertEqual(send_chat.call_args.args[1], [])


if __name__ == "__main__":
    unittest.main()
