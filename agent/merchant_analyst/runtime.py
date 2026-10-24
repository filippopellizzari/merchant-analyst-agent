"""Programmatic entry point shared by the CLI and the eval harness.

``ask()`` runs one question through an ADK ``Runner`` with an ``InMemorySessionService``
and folds the event stream into an ``AskResult`` (final answer text + paired tool calls).
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from merchant_analyst._env import load_env

load_env()


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    response: dict[str, Any]


@dataclass
class AskResult:
    question: str
    answer: str  # final text of the agent's last response
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    events: int = 0  # number of ADK events consumed

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def model_name(agent: BaseAgent) -> str:
    """Best-effort model name for an agent (``LlmAgent.model`` is a str or a BaseLlm)."""
    model = getattr(agent, "model", "")
    if isinstance(model, str):
        return model
    return str(getattr(model, "model", "") or type(model).__name__)


def _event_text(event: Event) -> str:
    if not event.content or not event.content.parts:
        return ""
    chunks = [p.text for p in event.content.parts if p.text and not getattr(p, "thought", False)]
    return "".join(chunks)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    return {"result": value}


def fold_events(question: str, events: list[Event], *, model: str = "") -> AskResult:
    """Pure function: pair function calls with their responses and extract the final answer.

    Pairing is by ``FunctionCall.id`` / ``FunctionResponse.id``; when ids are missing the
    oldest unmatched call with the same tool name is used. Calls without a response are
    kept with an empty response dict. The answer is the text of the last event for which
    ``event.is_final_response()`` is true and that carries text (falling back to the last
    text seen anywhere).
    """
    tool_calls: list[ToolCall] = []
    by_id: dict[str, ToolCall] = {}
    unmatched_by_name: dict[str, deque[ToolCall]] = {}
    answer = ""
    last_text = ""

    for event in events:
        for fc in event.get_function_calls():
            call = ToolCall(name=fc.name or "", args=_as_dict(fc.args), response={})
            tool_calls.append(call)
            if fc.id:
                by_id[fc.id] = call
            unmatched_by_name.setdefault(call.name, deque()).append(call)
        for fr in event.get_function_responses():
            call = by_id.pop(fr.id, None) if fr.id else None
            if call is None:
                queue = unmatched_by_name.get(fr.name or "")
                call = queue.popleft() if queue else None
                if call is not None:
                    for key, c in list(by_id.items()):
                        if c is call:
                            by_id.pop(key)
            else:
                queue = unmatched_by_name.get(call.name)
                if queue and call in queue:
                    queue.remove(call)
            if call is None:
                call = ToolCall(name=fr.name or "", args={}, response={})
                tool_calls.append(call)
            call.response = _as_dict(fr.response)
        text = _event_text(event)
        if text:
            last_text = text
            if event.is_final_response():
                answer = text

    return AskResult(
        question=question,
        answer=answer or last_text,
        tool_calls=tool_calls,
        model=model,
        events=len(events),
    )


async def ask(
    question: str,
    *,
    app_name: str = "merchant_analyst",
    user_id: str = "eval",
    session_id: str | None = None,
    agent: BaseAgent | None = None,
) -> AskResult:
    """Run ``question`` through ``agent`` (default: the merchant analyst root agent)."""
    if agent is None:
        from merchant_analyst.agent import root_agent

        agent = root_agent

    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=app_name, user_id=user_id, session_id=session_id or uuid.uuid4().hex
    )
    runner = Runner(app_name=app_name, agent=agent, session_service=session_service)
    message = types.Content(role="user", parts=[types.Part.from_text(text=question)])
    events: list[Event] = []
    try:
        async for event in runner.run_async(
            user_id=user_id, session_id=session.id, new_message=message
        ):
            events.append(event)
    finally:
        await runner.close()
    return fold_events(question, events, model=model_name(agent))


def ask_sync(question: str, **kwargs: Any) -> AskResult:
    """Blocking wrapper around :func:`ask` for scripts and the CLI."""
    return asyncio.run(ask(question, **kwargs))
