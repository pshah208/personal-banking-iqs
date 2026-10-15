"""Runs the Foundry agent as the signed-in user and streams progress as SSE.

WHY THIS TARGETS THE RESPONSES API
----------------------------------
Foundry has two agent surfaces. The older *assistants* API (threads / runs /
run-steps, exposed by the `azure-ai-agents` SDK) and the newer **prompt agent**
surface invoked through the OpenAI-compatible **Responses API**. An agent built
in the Foundry portal today is the latter, and it is invisible to the assistants
API - `list_agents()` returns an empty list even though the agent plainly exists.

So we call:

    POST {project}/openai/responses?api-version=2025-05-15-preview
    { "agent_reference": {"name": "<agent>"}, "input": "<question>", "stream": true }

Note `agent_reference`, not `agent` - the latter is deprecated and returns 400.

Streaming is a genuine win here: tool calls arrive as events, so the IQ cards
light up from the agent's real activity as it happens, with no polling.

TWO THINGS THIS DELIBERATELY DOES
---------------------------------
1. **On-Behalf-Of.** The call carries a token exchanged for the signed-in user, so
   Work IQ grounds on that user's mailbox, Teams and files - never the app identity.

2. **Citations kept separate from prose.** The Foundry playground splices citation
   markers in by character offset, which corrupts digits inside numbers and
   identifiers (`180 days` -> `[14]80 days`, `BR-202` -> `BR-[12]0[12]`). We return
   the answer text and its citations as separate fields and let the client render
   them, so numbers cannot be mangled.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncGenerator

import httpx

from .auth import User, exchange_obo
from .config import settings
from .iq import (
    classify,
    done_event,
    error_event,
    iq_event,
    is_invocation,
    message_event,
    sse,
    status_event,
    summarise_call,
    token_event,
)

logger = logging.getLogger("agent")

API_VERSION = "2025-05-15-preview"


def responses_url() -> str:
    base = settings.project_endpoint.rstrip("/")
    return f"{base}/openai/responses?api-version={API_VERSION}"


def _strip_markers(text: str) -> str:
    """Remove any citation placeholders the service embedded in the prose."""
    text = re.sub(r"%%CITATION_\d+%%", "", text)
    text = re.sub(r"【[^】]*】", "", text)
    return text


def _tool_label(item: dict) -> tuple[str, str]:
    """Best-effort (name, payload) for an output item representing a tool call."""
    kind = item.get("type", "") or ""
    name = (
        item.get("server_label")
        or item.get("name")
        or item.get("tool_name")
        or kind
    )
    payload = ""
    for key in ("arguments", "query", "input", "queries"):
        val = item.get(key)
        if val:
            payload = val if isinstance(val, str) else json.dumps(val)
            break
    return f"{kind} {name}".strip(), payload


def _item_error(item: dict) -> str:
    """Return a human-readable error for a tool call item, or '' if it succeeded.

    A failed MCP call still arrives as a normal output item - the only signal is
    a populated `error`. Foundry sometimes reports it as a bare string
    ("MCP tool call failed") and sometimes as an object, so both are handled.
    """
    err = item.get("error")
    if not err:
        return ""
    label = item.get("server_label") or item.get("name") or item.get("type") or "tool"
    if isinstance(err, dict):
        text = err.get("message") or err.get("code") or json.dumps(err)
    else:
        text = str(err)
    return f"{label}: {text}"


def _collect_tool_errors(payload: dict) -> list[str]:
    """Every tool failure in a completed response, in call order."""
    out: list[str] = []
    for item in payload.get("output", []) or []:
        if isinstance(item, dict):
            msg = _item_error(item)
            if msg and msg not in out:
                out.append(msg)
    return out


def _empty_answer_detail(tool_errors: list[str], status: str) -> str:
    """Explain an empty answer using whatever the run actually told us."""
    if tool_errors:
        return ("A grounding tool failed, so the agent had nothing to answer from: "
                + "; ".join(tool_errors))
    return (
        f"The agent completed (status={status or 'unknown'}) but produced no text, "
        "and no tool reported an error. The grounding tools most likely returned "
        "zero results for your identity - Work IQ and Fabric IQ are security "
        "trimmed, so check that this user has a provisioned mailbox, Teams "
        "membership and Fabric workspace access."
    )


def _collect_citations(payload: dict) -> list[dict]:
    """Pull url/file citation annotations out of a completed response."""
    out: list[dict] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") in ("url_citation", "file_citation"):
                key = node.get("url") or node.get("file_id") or node.get("title", "")
                if key and key not in seen:
                    seen.add(key)
                    out.append({
                        "kind": "url" if node.get("type") == "url_citation" else "file",
                        "title": node.get("title") or node.get("filename") or "",
                        "url": node.get("url", ""),
                        "fileId": node.get("file_id", ""),
                    })
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(payload)
    return out


def _extract_text(payload: dict) -> str:
    """Concatenate the assistant's output text from a completed response."""
    if isinstance(payload.get("output_text"), str) and payload["output_text"]:
        return payload["output_text"]
    parts: list[str] = []
    for item in payload.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for c in item.get("content", []) or []:
            if c.get("type") in ("output_text", "text") and c.get("text"):
                parts.append(c["text"])
    return "".join(parts)


def _tool_call_event(item: dict) -> str:
    """One frame per tool invocation, for the mission harness trace (iq_active only fires once per layer)."""
    name, payload = _tool_label(item)
    return sse("tool_call", {"iq": classify(name, payload), "tool": item.get("server_label") or item.get("name") or item.get("type", ""),
                             "detail": summarise_call(name, payload), "error": _item_error(item)})


async def run_agent(user: User, question: str,
                    thread_id: str | None = None,
                    agent_name: str | None = None,
                    trace: bool = False) -> AsyncGenerator[str, None]:
    """Yield SSE frames for one question. `trace` adds a `tool_call` frame for every tool invocation."""
    if settings.mock_mode:
        async for frame in _mock(question):
            yield frame
        return

    try:
        yield status_event("Authenticating on your behalf…")
        token = await exchange_obo(user)
    except Exception as exc:  # noqa: BLE001
        yield error_event("Could not authenticate to the agent.",
                          str(getattr(exc, "detail", exc))[:600])
        yield done_event(ok=False)
        return

    body: dict[str, Any] = {
        # Both keys are required. `agent_reference` replaces the deprecated
        # `agent` property, and the nested object must carry its own "type" -
        # omitting it returns 400 invalid_payload.
        "agent_reference": {
            "type": "agent_reference",
            "name": agent_name or settings.agent_name,
        },
        "input": question,
        "stream": True,
    }
    # Continue the conversation when we have a prior response id.
    if thread_id:
        body["previous_response_id"] = thread_id

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    active: set[str] = set()
    seen_calls: set[str] = set()
    traced: set[str] = set()
    text_acc = ""
    citations: list[dict] = []
    response_id = thread_id
    tool_errors: list[str] = []
    final_status = ""

    yield status_event("Thinking…")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
            async with client.stream("POST", responses_url(),
                                     headers=headers, json=body) as resp:
                if resp.status_code >= 400:
                    raw = (await resp.aread()).decode("utf-8", "replace")
                    async for frame in _fallback_nonstreaming(
                        client, headers, body, active, raw, trace
                    ):
                        yield frame
                    return

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        evt = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    etype = evt.get("type", "")

                    # Streamed prose. Forwarded to the browser as it arrives, not
                    # just accumulated: a grounded answer here takes tens of
                    # seconds, almost all of it tool latency, and holding the
                    # text back turns that into a blank spinner. Streaming does
                    # not make the answer faster - it makes the wait legible,
                    # which is the part an audience feels.
                    #
                    # `text_acc` is still maintained because the final `message`
                    # event carries the whole answer plus its citations, and the
                    # client replaces the streamed text with it. That keeps the
                    # citation-separation guarantee intact: nothing is ever
                    # spliced into a partial string.
                    if etype.endswith("output_text.delta"):
                        delta = evt.get("delta", "") or ""
                        if delta:
                            text_acc += delta
                            yield token_event(delta)
                        continue

                    # A tool actually ran -> light up its IQ layer. Discovery
                    # events (mcp_list_tools) are filtered out by is_invocation,
                    # otherwise every layer would glow on every question.
                    if "output_item" in etype or "tool" in etype:
                        item = evt.get("item") or evt.get("output_item") or {}
                        if isinstance(item, dict) and item:
                            item_type = item.get("type", "")
                            if not is_invocation(item_type):
                                continue
                            # A failed tool is the single most useful thing we
                            # can report, so capture it even if we cannot map
                            # the call onto an IQ layer.
                            err = _item_error(item)
                            if err and err not in tool_errors:
                                tool_errors.append(err)
                                logger.warning("tool failed for %s: %s", user.upn, err)
                            key = item.get("id") or json.dumps(item)[:80]
                            # `.done` carries the final arguments; `.added` often has none yet.
                            if trace and etype.endswith("output_item.done") and key not in traced:
                                traced.add(key)
                                yield _tool_call_event(item)
                            if key not in seen_calls:
                                seen_calls.add(key)
                                name, payload = _tool_label(item)
                                iq = classify(name, payload)
                                if iq and iq not in active:
                                    active.add(iq)
                                    yield iq_event(iq, "active",
                                                   summarise_call(name, payload))

                    if etype.endswith("response.completed"):
                        payload = evt.get("response", evt)
                        response_id = payload.get("id", response_id)
                        final_status = payload.get("status", "") or final_status
                        citations = _collect_citations(payload)
                        for err in _collect_tool_errors(payload):
                            if err not in tool_errors:
                                tool_errors.append(err)
                        full = _extract_text(payload)
                        if full:
                            text_acc = full
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent stream failed")
        for iq in list(active):
            yield iq_event(iq, "done", "stopped")
        yield error_event("The agent could not complete this request.", str(exc)[:600])
        yield done_event(ok=False)
        return

    for iq in active:
        yield iq_event(iq, "done", "complete")

    text = _strip_markers(text_acc).strip()

    # An empty answer used to render as silence, which looks like the app is
    # broken rather than the grounding being empty or failing. Say so instead.
    if not text:
        logger.warning("empty answer for %s (status=%s, tool_errors=%s)",
                       user.upn, final_status or "?", tool_errors or "none")
        yield error_event(
            "The agent ran but returned no answer.",
            _empty_answer_detail(tool_errors, final_status)[:900],
        )
        yield done_event(ok=False, threadId=response_id, layers=sorted(active),
                         toolErrors=tool_errors)
        return

    if tool_errors:
        logger.warning("partial answer for %s, tool errors: %s", user.upn, tool_errors)

    yield message_event(text, citations)
    yield done_event(ok=True, threadId=response_id, layers=sorted(active),
                     toolErrors=tool_errors)


async def _fallback_nonstreaming(client: httpx.AsyncClient, headers: dict,
                                 body: dict, active: set[str],
                                 stream_error: str, trace: bool = False) -> AsyncGenerator[str, None]:
    """If streaming is rejected, retry once without it before giving up."""
    logger.warning("stream rejected, retrying without stream: %s", stream_error[:300])
    payload = dict(body)
    payload.pop("stream", None)
    try:
        r = await client.post(responses_url(), headers=headers, json=payload)
        if r.status_code >= 400:
            yield error_event("The agent rejected the request.",
                              f"{r.status_code}: {r.text[:500]}")
            yield done_event(ok=False)
            return
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        yield error_event("The agent could not be reached.", str(exc)[:500])
        yield done_event(ok=False)
        return

    # No streamed events, so derive the layers from the tools the response used.
    tool_errors = _collect_tool_errors(data)
    for item in data.get("output", []) or []:
        if not isinstance(item, dict) or not is_invocation(item.get("type", "")):
            continue
        if trace:
            yield _tool_call_event(item)
        name, arg = _tool_label(item)
        iq = classify(name, arg)
        if iq and iq not in active:
            active.add(iq)
            yield iq_event(iq, "active", summarise_call(name, arg))

    for iq in active:
        yield iq_event(iq, "done", "complete")

    text = _strip_markers(_extract_text(data)).strip()
    if not text:
        logger.warning("empty answer (non-streaming), tool_errors=%s",
                       tool_errors or "none")
        yield error_event(
            "The agent ran but returned no answer.",
            _empty_answer_detail(tool_errors, data.get("status", ""))[:900],
        )
        yield done_event(ok=False, threadId=data.get("id"),
                         layers=sorted(active), toolErrors=tool_errors)
        return

    yield message_event(text, _collect_citations(data))
    yield done_event(ok=True, threadId=data.get("id"), layers=sorted(active),
                     toolErrors=tool_errors)


# --------------------------------------------------------------------------- #
async def _mock(question: str) -> AsyncGenerator[str, None]:
    """Offline path so the UI can be built without Azure."""
    q = question.lower()
    layers = []
    if any(w in q for w in ("said", "discussion", "concern", "escalat", "feedback",
                            "email", "teams", "meeting", "raised")):
        layers.append("work")
    if any(w in q for w in ("how many", "risk", "exposure", "segment", "balance",
                            "customer", "renewal", "value")):
        layers.append("fabric")
    if any(w in q for w in ("polic", "approv", "guardrail", "osfi", "allowed",
                            "evidence", "pricing")):
        layers.append("foundry")
    layers = layers or ["fabric"]

    yield status_event("Thinking…")
    for iq in layers:
        await asyncio.sleep(0.7)
        yield iq_event(iq, "active")
    await asyncio.sleep(0.7)
    for iq in layers:
        yield iq_event(iq, "done", "complete")

    yield message_event(
        "**Mock mode.** The BFF is running without Azure credentials, so this is a "
        "canned answer.\n\nLayers that would have been used: "
        + ", ".join(layers)
        + ".\n\nSet `MOCK_MODE=false` and configure the Entra and Foundry settings "
          "to get grounded answers.",
        [],
    )
    yield done_event(ok=True, layers=layers)
