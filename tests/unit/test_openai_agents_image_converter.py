"""Regression tests for OpenAI Agents tool-output image conversion."""

from contextlib import contextmanager
from typing import Iterator, Literal

from agents import Agent, set_default_openai_api
from agents.models import _openai_shared
from agents.models.openai_chatcompletions import Converter
from agents.run import CallModelData, ModelInputData
from omegaconf import OmegaConf

from scenesmith.agent_utils.chat_completions_image_filter import (
    ChatCompletionsToolImageFilter,
    CompositeCallModelInputFilter,
)
from scenesmith.agent_utils.intra_turn_image_filter import IntraTurnImageFilter


def _image_tool_output_item() -> dict:
    return {
        "type": "function_call_output",
        "call_id": "call_observe_scene",
        "output": [
            {"type": "input_text", "text": "Scene render"},
            {
                "type": "input_image",
                "image_url": "data:image/png;base64,iVBORw0KGgo=",
                "detail": "auto",
            },
        ],
    }


def _make_call_data(items: list[dict]) -> CallModelData:
    return CallModelData(
        model_data=ModelInputData(input=items, instructions=None),
        agent=Agent(name="test_agent", model="gpt-4o-mini"),
        context=None,
    )


@contextmanager
def _default_openai_api(
    api: Literal["chat_completions", "responses"],
) -> Iterator[None]:
    previous_uses_responses = _openai_shared.get_use_responses_by_default()
    set_default_openai_api(api)
    try:
        yield
    finally:
        set_default_openai_api(
            "responses" if previous_uses_responses else "chat_completions"
        )


def test_chat_completions_converter_can_preserve_tool_output_images() -> None:
    """openai-agents >=0.6.5 exposes the opt-in preservation path for images."""
    messages = Converter.items_to_messages(
        [_image_tool_output_item()], preserve_tool_output_all_content=True
    )

    assert messages == [
        {
            "role": "tool",
            "tool_call_id": "call_observe_scene",
            "content": [
                {"type": "text", "text": "Scene render"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,iVBORw0KGgo=",
                        "detail": "auto",
                    },
                },
            ],
        }
    ]


def test_chat_completions_filter_lifts_tool_images_to_user_message() -> None:
    """Plain OpenAI Chat Completions sees tool images via a follow-up user item."""
    with _default_openai_api("chat_completions"):
        filtered = ChatCompletionsToolImageFilter()(
            _make_call_data([_image_tool_output_item()])
        )

    messages = Converter.items_to_messages(filtered.input)

    assert messages == [
        {
            "role": "tool",
            "tool_call_id": "call_observe_scene",
            "content": "Scene render",
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Images returned by the previous tool call(s):",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,iVBORw0KGgo=",
                        "detail": "auto",
                    },
                },
            ],
        },
    ]


def test_chat_completions_filter_is_noop_for_responses_default() -> None:
    """The default Responses API path already preserves image tool outputs."""
    with _default_openai_api("responses"):
        filtered = ChatCompletionsToolImageFilter()(
            _make_call_data([_image_tool_output_item()])
        )

    assert filtered.input == [_image_tool_output_item()]


def test_composed_filters_strip_old_images_then_lift_remaining_images() -> None:
    """Memory stripping still runs before Chat Completions image lifting."""
    cfg = OmegaConf.create(
        {
            "session_memory": {
                "intra_turn_observation_stripping": {
                    "enabled": True,
                    "keep_last_n_observations": 1,
                }
            }
        }
    )
    old_observation = _image_tool_output_item()
    old_observation["call_id"] = "call_old"
    new_observation = _image_tool_output_item()
    new_observation["call_id"] = "call_new"
    items = [old_observation, new_observation]

    with _default_openai_api("chat_completions"):
        filtered = CompositeCallModelInputFilter(
            [
                IntraTurnImageFilter(cfg=cfg),
                ChatCompletionsToolImageFilter(),
            ]
        )(_make_call_data(items))

    assert len(filtered.input) == 3
    assert filtered.input[0]["call_id"] == "call_old"
    assert filtered.input[0]["output"] == "Scene render\n[image removed]"
    assert filtered.input[1]["call_id"] == "call_new"
    assert filtered.input[1]["output"] == "Scene render"
    assert filtered.input[2]["role"] == "user"
    assert filtered.input[2]["content"][1]["type"] == "input_image"

    assert old_observation["output"][1]["type"] == "input_image"
    assert new_observation["output"][1]["type"] == "input_image"


def test_chat_completions_filter_keeps_multi_tool_results_adjacent() -> None:
    """Image messages are added after a contiguous block of tool outputs."""
    first_observation = _image_tool_output_item()
    first_observation["call_id"] = "call_first"
    second_observation = _image_tool_output_item()
    second_observation["call_id"] = "call_second"

    with _default_openai_api("chat_completions"):
        filtered = ChatCompletionsToolImageFilter()(
            _make_call_data([first_observation, second_observation])
        )

    messages = Converter.items_to_messages(filtered.input)

    assert [message["role"] for message in messages] == ["tool", "tool", "user"]
    assert messages[0]["tool_call_id"] == "call_first"
    assert messages[0]["content"] == "Scene render"
    assert messages[1]["tool_call_id"] == "call_second"
    assert messages[1]["content"] == "Scene render"
    assert messages[2]["content"][1]["type"] == "image_url"
    assert messages[2]["content"][2]["type"] == "image_url"


def test_chat_completions_filter_flattens_text_tool_content_for_azure() -> None:
    """Azure Chat Completions rejects structured content in tool messages."""
    item = {
        "type": "function_call_output",
        "call_id": "call_text_parts",
        "output": [
            {"type": "input_text", "text": "First line"},
            {"type": "input_text", "text": "Second line"},
        ],
    }

    with _default_openai_api("chat_completions"):
        filtered = ChatCompletionsToolImageFilter()(_make_call_data([item]))

    messages = Converter.items_to_messages(filtered.input)

    assert messages == [
        {
            "role": "tool",
            "tool_call_id": "call_text_parts",
            "content": "First line\nSecond line",
        }
    ]
