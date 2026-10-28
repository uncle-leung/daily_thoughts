#!/usr/bin/env python3
"""Run a Cursor cloud agent that must search the web before it answers."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

API_ROOT = "https://api.cursor.com"
DEFAULT_MODEL = "grok-4.7"
DEFAULT_PARAMS = (
    {"id": "context", "value": "256k"},
    {"id": "reasoning_effort", "value": "high"},
    {"id": "fast", "value": "true"},
)
SEARCH_TOOLS = frozenset({"web_search", "web_fetch"})
USER_AGENT = "daily-thoughts-cursor/1.0"


class CursorResearchError(Exception):
    """The cloud agent did not return a searched answer."""


def api_key() -> str:
    return os.environ.get("CURSOR_API_KEY", "").strip()


def model_selection() -> dict[str, object]:
    model_id = os.environ.get("CURSOR_MODEL", "").strip() or DEFAULT_MODEL
    return {"id": model_id, "params": [dict(item) for item in DEFAULT_PARAMS]}


def timeout_seconds() -> float:
    raw = os.environ.get("CURSOR_AGENT_TIMEOUT_SEC", "").strip()
    if not raw:
        return 900.0
    try:
        value = float(raw)
    except ValueError:
        return 900.0
    return max(30.0, value)


def _redact(text: str) -> str:
    secret = api_key()
    if secret and secret in text:
        return text.replace(secret, "[redacted]")
    return text


def _auth_header() -> str:
    token = base64.b64encode(f"{api_key()}:".encode()).decode("ascii")
    return f"Basic {token}"


def parse_sse(blob: str) -> list[tuple[str, dict]]:
    """Parse one SSE document into (event, payload) pairs."""
    events: list[tuple[str, dict]] = []
    event = "message"
    data: list[str] = []

    def flush() -> None:
        nonlocal event, data
        if not data:
            event = "message"
            return
        raw = "\n".join(data)
        data = []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            events.append((event, payload))
        event = "message"

    for line in blob.splitlines():
        if line.startswith(":"):
            continue
        if line == "":
            flush()
            continue
        if line.startswith("event:"):
            event = line[6:].strip() or "message"
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
    flush()
    return events


def completed_search_tools(events: list[tuple[str, dict]]) -> list[str]:
    names: list[str] = []
    for name, payload in events:
        if name != "tool_call" or payload.get("status") != "completed":
            continue
        tool = str(payload.get("name") or "")
        if tool in SEARCH_TOOLS:
            names.append(tool)
    return names


def require_live_search(tools: list[str]) -> None:
    found = set(tools)
    if "web_search" not in found or "web_fetch" not in found:
        raise CursorResearchError("agent answered without web_search and web_fetch")


def result_text(events: list[tuple[str, dict]]) -> str:
    for name, payload in reversed(events):
        if name == "result" and payload.get("status") == "FINISHED":
            return str(payload.get("text") or "")
        if name == "status" and payload.get("status") in {"ERROR", "CANCELLED", "EXPIRED"}:
            detail = str(payload.get("text") or payload.get("message") or payload.get("status"))
            raise CursorResearchError(f"agent run {payload.get('status')}: {detail[:300]}")
    return ""


def _request(method: str, path: str, body: dict | None = None, accept: str = "application/json"):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        API_ROOT + path,
        data=data,
        method=method,
        headers={
            "Authorization": _auth_header(),
            "Accept": accept,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        return urllib.request.urlopen(request, timeout=60)
    except urllib.error.HTTPError as exc:
        detail = _redact(exc.read().decode("utf-8", errors="replace"))
        raise CursorResearchError(f"cursor api {exc.code}: {detail[:400]}") from None


def _open_stream(agent_id: str, run_id: str):
    request = urllib.request.Request(
        f"{API_ROOT}/v1/agents/{agent_id}/runs/{run_id}/stream",
        headers={
            "Authorization": _auth_header(),
            "Accept": "text/event-stream",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        return urllib.request.urlopen(request, timeout=timeout_seconds())
    except urllib.error.HTTPError as exc:
        detail = _redact(exc.read().decode("utf-8", errors="replace"))
        raise CursorResearchError(f"cursor stream {exc.code}: {detail[:400]}") from None


def _read_stream(response, deadline: float) -> list[tuple[str, dict]]:
    event = "message"
    data: list[str] = []
    found: list[tuple[str, dict]] = []

    def flush() -> bool:
        nonlocal event, data
        if not data:
            event = "message"
            return False
        raw = "\n".join(data)
        data = []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        current = event
        event = "message"
        if not isinstance(payload, dict):
            return False
        found.append((current, payload))
        return current == "result"

    while time.monotonic() < deadline:
        line = response.readline()
        if not line:
            flush()
            break
        text = line.decode("utf-8", errors="replace").rstrip("\r\n")
        if text.startswith(":"):
            continue
        if text == "":
            if flush():
                break
            continue
        if text.startswith("event:"):
            event = text[6:].strip() or "message"
        elif text.startswith("data:"):
            data.append(text[5:].lstrip())
    else:
        raise CursorResearchError("cursor agent timed out")
    return found


def _fetch_run(agent_id: str, run_id: str) -> dict:
    with _request("GET", f"/v1/agents/{agent_id}/runs/{run_id}") as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise CursorResearchError("cursor run payload was not an object")
    return payload


def run_research(prompt: str, name: str) -> tuple[str, list[str]]:
    """Launch a no-repo cloud agent and return its reply plus search tools it finished."""
    if not api_key():
        raise CursorResearchError("CURSOR_API_KEY is not set")
    created_body = {
        "name": name[:100],
        "mode": "agent",
        "model": model_selection(),
        "prompt": {"text": prompt},
    }
    with _request("POST", "/v1/agents", created_body) as response:
        created = json.load(response)
    agent = created.get("agent") or {}
    run = created.get("run") or {}
    agent_id = str(agent.get("id") or "")
    run_id = str(run.get("id") or "")
    if not agent_id or not run_id:
        raise CursorResearchError("cursor api did not return an agent run")
    print(f"cursor agent {agent_id} model {model_selection()['id']}")
    deadline = time.monotonic() + timeout_seconds()
    try:
        with _open_stream(agent_id, run_id) as stream:
            events = _read_stream(stream, deadline)
    except TimeoutError:
        raise CursorResearchError("cursor agent timed out") from None
    except urllib.error.URLError as exc:
        raise CursorResearchError(f"cursor stream failed: {exc}") from None
    text = ""
    try:
        text = result_text(events)
    except CursorResearchError:
        raise
    if not text:
        payload = _fetch_run(agent_id, run_id)
        status = str(payload.get("status") or "")
        if status != "FINISHED":
            raise CursorResearchError(f"cursor run ended as {status or 'unknown'}")
        text = str(payload.get("result") or "")
    tools = completed_search_tools(events)
    require_live_search(tools)
    if not text.strip():
        raise CursorResearchError("cursor agent returned an empty answer")
    return text, tools
