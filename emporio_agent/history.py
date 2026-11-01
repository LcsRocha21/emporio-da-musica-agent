"""Saving, resuming and exporting conversations.

A session is one JSON file in ``chat_history/`` (git-ignored, since it holds customer
data). Only the plain conversation is stored: user and assistant text, plus the tool
calls and results for the record. The provider's opaque state (Gemini thought
signatures) is never saved; the Gemini adapter replays resumed turns as plain text.
"""

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from emporio_agent import config
from emporio_agent.llm.base import Message, ToolCall, ToolResult
from emporio_agent.prompt import greeting

FORMAT_VERSION = 1
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_RESULT_PREVIEW_CHARS = 240


class HistoryError(RuntimeError):
    """A session could not be named, read or written."""


@dataclass
class Session:
    customer_name: str | None
    messages: list[Message]


def new_session_id() -> str:
    # Real clock on purpose: EMPORIO_NOW freezes the store clock and would make ids collide.
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def session_path(session_id: str, directory: Path | None = None) -> Path:
    if not _SESSION_ID.match(session_id):
        raise HistoryError("Session names may only contain letters, digits, '-' and '_' (up to 64 characters).")
    return (directory or config.CHAT_HISTORY_DIR) / f"{session_id}.json"


def latest_session(directory: Path | None = None) -> Path | None:
    """The most recently saved session, or None."""
    folder = directory or config.CHAT_HISTORY_DIR
    files = [p for p in folder.glob("*.json") if p.is_file()] if folder.is_dir() else []
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def message_to_dict(message: Message) -> dict:
    data: dict = {"role": message.role}
    if message.text is not None:
        data["text"] = message.text
    if message.tool_calls:
        data["tool_calls"] = [{"name": c.name, "args": c.args, "id": c.id} for c in message.tool_calls]
    if message.tool_results:
        data["tool_results"] = [{"name": r.name, "result": r.result, "id": r.id} for r in message.tool_results]
    return data


def message_from_dict(data: dict) -> Message:
    return Message(
        role=data["role"],
        text=data.get("text"),
        tool_calls=[ToolCall(c["name"], c.get("args") or {}, c.get("id")) for c in data.get("tool_calls", [])],
        tool_results=[ToolResult(r["name"], r.get("result"), r.get("id")) for r in data.get("tool_results", [])],
    )


def save_session(path: Path, messages: list[Message], customer_name: str | None = None) -> None:
    """Write the session atomically, so a crash never leaves a half-written file."""
    payload = {
        "version": FORMAT_VERSION,
        "customer_name": customer_name,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "messages": [message_to_dict(m) for m in messages],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except OSError as error:
        raise HistoryError(f"Could not save the conversation to {path}: {error}") from error


def load_session(path: Path) -> Session:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return Session(
            customer_name=payload.get("customer_name"),
            messages=[message_from_dict(item) for item in payload["messages"]],
        )
    except OSError as error:
        raise HistoryError(f"Could not read {path}: {error}") from error
    except (ValueError, KeyError, TypeError) as error:
        raise HistoryError(f"{path.name} is not a valid saved conversation ({error}).") from error


def _preview(value) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= _RESULT_PREVIEW_CHARS else text[: _RESULT_PREVIEW_CHARS - 1] + "…"


def export_markdown(messages: list[Message], customer_name: str | None = None, title: str = "Conversa com o DJ") -> str:
    """A readable transcript: what the customer said, which tools ran, what DJ answered."""
    lines = [f"# {title}", ""]
    lines += [f"**DJ:** {greeting(customer_name)}", ""]
    pending: list[tuple[ToolCall, ToolResult | None]] = []
    for message in messages:
        if message.role == "user":
            lines += [f"**Você:** {message.text}", ""]
        elif message.role == "assistant":
            for call in message.tool_calls:
                pending.append((call, None))
            if message.text and not message.tool_calls:
                lines += _tool_block(pending)
                pending = []
                lines += [f"**DJ:** {message.text}", ""]
        elif message.role == "tool":
            for index, result in enumerate(message.tool_results):
                start = len(pending) - len(message.tool_results)
                if 0 <= start + index < len(pending):
                    pending[start + index] = (pending[start + index][0], result)
    lines += _tool_block(pending)
    return "\n".join(lines).rstrip() + "\n"


def _tool_block(pending: list[tuple[ToolCall, ToolResult | None]]) -> list[str]:
    if not pending:
        return []
    lines = ["<details><summary>Ferramentas usadas</summary>", ""]
    for call, result in pending:
        lines.append(f"- `{call.name}({json.dumps(call.args, ensure_ascii=False)})`")
        if result is not None:
            lines.append(f"  → `{_preview(result.result)}`")
    lines += ["", "</details>", ""]
    return lines
