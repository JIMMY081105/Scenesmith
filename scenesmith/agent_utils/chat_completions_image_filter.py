"""Chat Completions compatibility for image-returning tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents import OpenAIChatCompletionsModel
from agents.items import TResponseInputItem
from agents.models import _openai_shared
from agents.run import CallModelData, ModelInputData

from scenesmith.agent_utils.turn_trimming_session import _is_image_content


def _uses_openai_chat_completions(data: CallModelData[Any]) -> bool:
    """Return true when the current run will use OpenAI Chat Completions."""
    if isinstance(data.agent.model, OpenAIChatCompletionsModel):
        return True

    # SceneSmith creates agents with model names. In that case, the Agents SDK
    # resolves the backend through the default OpenAI provider.
    if isinstance(data.agent.model, str) or data.agent.model is None:
        return not _openai_shared.get_use_responses_by_default()

    return False


@dataclass
class ChatCompletionsToolImageFilter:
    """Expose tool-output images to Chat Completions models.

    OpenAI Chat Completions only allows text content in tool messages. When
    tools return images, keep tool messages text-only and add a synthetic user
    message with the images after each contiguous block of tool results.
    """

    force_enable: bool = False

    def __call__(self, data: CallModelData[Any]) -> ModelInputData:
        if not self.force_enable and not _uses_openai_chat_completions(data):
            return data.model_data

        transformed: list[TResponseInputItem] = []
        pending_image_parts: list[dict[str, Any]] = []
        changed = False

        for item in data.model_data.input:
            if not self._is_function_call_output(item):
                self._flush_pending_images(transformed, pending_image_parts)
                transformed.append(item)
                continue

            tool_item, image_parts = self._split_image_tool_output(item)
            transformed.append(tool_item)
            pending_image_parts.extend(image_parts)
            changed = changed or tool_item is not item or bool(image_parts)

        self._flush_pending_images(transformed, pending_image_parts)

        if not changed:
            return data.model_data

        return ModelInputData(
            input=transformed, instructions=data.model_data.instructions
        )

    def _is_function_call_output(self, item: TResponseInputItem) -> bool:
        if not isinstance(item, dict):
            return False
        return item.get("type") == "function_call_output"

    def _is_list_tool_output(self, item: TResponseInputItem) -> bool:
        if not self._is_function_call_output(item):
            return False
        assert isinstance(item, dict)
        output = item.get("output")
        return isinstance(output, list)

    def _split_image_tool_output(
        self, item: TResponseInputItem
    ) -> tuple[TResponseInputItem, list[dict[str, Any]]]:
        if not self._is_list_tool_output(item):
            return item, []

        assert isinstance(item, dict)  # Narrowed by _is_list_tool_output.
        output = item.get("output")
        assert isinstance(output, list)

        image_parts = [
            part
            for part in output
            if isinstance(part, dict) and _is_image_content(part)
        ]
        text_parts = [
            part
            for part in output
            if not (isinstance(part, dict) and _is_image_content(part))
        ]

        tool_item = dict(item)
        if text_parts:
            tool_item["output"] = self._text_parts_to_string(text_parts)
        else:
            tool_item["output"] = (
                "The tool returned image output. The image content is attached in "
                "the following user message."
            )

        return tool_item, image_parts

    def _text_parts_to_string(self, text_parts: list[Any]) -> str:
        text_segments = []
        for part in text_parts:
            if isinstance(part, str):
                text_segments.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    text_segments.append(text)
                else:
                    text_segments.append(str(part))
            else:
                text_segments.append(str(part))

        return (
            "\n".join(segment for segment in text_segments if segment)
            or "[Tool output]"
        )

    def _flush_pending_images(
        self,
        transformed: list[TResponseInputItem],
        pending_image_parts: list[dict[str, Any]],
    ) -> None:
        if not pending_image_parts:
            return

        image_message: TResponseInputItem = {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Images returned by the previous tool call(s):",
                },
                *pending_image_parts,
            ],
        }
        transformed.append(image_message)
        pending_image_parts.clear()


@dataclass
class CompositeCallModelInputFilter:
    """Apply multiple call_model_input_filter functions in order."""

    filters: list[Any]

    def __call__(self, data: CallModelData[Any]) -> ModelInputData:
        model_data = data.model_data
        for input_filter in self.filters:
            model_data = input_filter(
                CallModelData(
                    model_data=model_data,
                    agent=data.agent,
                    context=data.context,
                )
            )
        return model_data
