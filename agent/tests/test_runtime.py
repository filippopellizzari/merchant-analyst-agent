"""runtime.ask() with a stub BaseAgent that never touches Gemini, plus fold_events alone."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import ClassVar

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from merchant_analyst.runtime import AskResult, ToolCall, ask, ask_sync, fold_events

SUMMARY = {
    "revenue": 362165.12,
    "orders": 5692,
    "meta": {"clamped": False, "date_range_applied": {"start_date": "2020-12-01", "end_date": "2020-12-31"}},
}


def _call_event(inv: str, author: str, call_id: str, name: str, args: dict) -> Event:
    return Event(
        invocation_id=inv,
        author=author,
        content=types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(id=call_id, name=name, args=args))],
        ),
    )


def _response_event(inv: str, author: str, call_id: str, name: str, response: dict) -> Event:
    return Event(
        invocation_id=inv,
        author=author,
        content=types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=call_id, name=name, response=response
                    )
                )
            ],
        ),
    )


def _text_event(inv: str, author: str, text: str, partial: bool | None = None) -> Event:
    return Event(
        invocation_id=inv,
        author=author,
        partial=partial,
        content=types.Content(role="model", parts=[types.Part.from_text(text=text)]),
    )


class ScriptedAgent(BaseAgent):
    """Yields a scripted call -> response -> answer sequence; records the question it saw."""

    model: str = "stub-model"
    seen_questions: ClassVar[list[str]] = []

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        question = ""
        if ctx.user_content and ctx.user_content.parts:
            question = ctx.user_content.parts[0].text or ""
        ScriptedAgent.seen_questions.append(question)
        inv = ctx.invocation_id
        yield _call_event(
            inv, self.name, "c1", "get_sales_summary",
            {"start_date": "2020-12-01", "end_date": "2020-12-31"},
        )
        yield _response_event(inv, self.name, "c1", "get_sales_summary", SUMMARY)
        yield _text_event(inv, self.name, "Revenue was ", partial=True)
        yield _text_event(inv, self.name, "Revenue in 2020-12-01..2020-12-31 was $362,165.12.")


def test_ask_pairs_calls_and_extracts_answer():
    ScriptedAgent.seen_questions.clear()
    agent = ScriptedAgent(name="scripted")
    result = asyncio.run(ask("revenue in December?", agent=agent, app_name="scripted"))
    assert isinstance(result, AskResult)
    assert result.question == "revenue in December?"
    assert ScriptedAgent.seen_questions == ["revenue in December?"]
    assert result.answer == "Revenue in 2020-12-01..2020-12-31 was $362,165.12."
    assert result.model == "stub-model"
    assert result.events == 4
    assert result.tool_calls == [
        ToolCall(
            name="get_sales_summary",
            args={"start_date": "2020-12-01", "end_date": "2020-12-31"},
            response=SUMMARY,
        )
    ]


def test_ask_sync_wrapper():
    result = ask_sync("again?", agent=ScriptedAgent(name="scripted"), app_name="scripted")
    assert result.answer.endswith("$362,165.12.")
    assert result.to_dict()["tool_calls"][0]["name"] == "get_sales_summary"


def test_fold_events_pairs_by_id_not_order():
    inv = "inv"
    events = [
        _call_event(inv, "a", "x1", "get_funnel", {"start_date": "a", "end_date": "b"}),
        _call_event(inv, "a", "x2", "get_geo_breakdown", {"start_date": "a", "end_date": "b"}),
        _response_event(inv, "a", "x2", "get_geo_breakdown", {"rows": []}),
        _response_event(inv, "a", "x1", "get_funnel", {"steps": [1, 2]}),
        _text_event(inv, "a", "done"),
    ]
    result = fold_events("q", events, model="m")
    assert [c.name for c in result.tool_calls] == ["get_funnel", "get_geo_breakdown"]
    assert result.tool_calls[0].response == {"steps": [1, 2]}
    assert result.tool_calls[1].response == {"rows": []}
    assert result.answer == "done" and result.events == 5 and result.model == "m"


def test_fold_events_falls_back_to_name_fifo_without_ids():
    inv = "inv"
    events = [
        _call_event(inv, "a", None, "get_funnel", {"n": 1}),
        _call_event(inv, "a", None, "get_funnel", {"n": 2}),
        _response_event(inv, "a", None, "get_funnel", {"r": 1}),
        _response_event(inv, "a", None, "get_funnel", {"r": 2}),
        _text_event(inv, "a", "ok"),
    ]
    result = fold_events("q", events)
    assert [(c.args, c.response) for c in result.tool_calls] == [({"n": 1}, {"r": 1}), ({"n": 2}, {"r": 2})]


def test_fold_events_unanswered_call_and_no_final_text():
    inv = "inv"
    events = [
        _text_event(inv, "a", "thinking...", partial=True),
        _call_event(inv, "a", "c", "get_dataset_info", {}),
    ]
    result = fold_events("q", events)
    assert result.tool_calls == [ToolCall(name="get_dataset_info", args={}, response={})]
    assert result.answer == "thinking..."  # fallback to last text seen


def test_fold_events_non_dict_response_is_wrapped():
    inv = "inv"
    events = [
        _call_event(inv, "a", "c", "get_dataset_info", {}),
        Event(
            invocation_id=inv,
            author="a",
            content=types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id="c", name="get_dataset_info", response={"result": "plain"}
                        )
                    )
                ],
            ),
        ),
    ]
    result = fold_events("q", events)
    assert result.tool_calls[0].response == {"result": "plain"}
