
import json
import os
from typing import Any

from dotenv import load_dotenv

from tools.agent_context import runtime_env_path_override
from tools.paths import agent_dir

load_dotenv()


def _resolve_runtime_env_path() -> str:
    """Resolve runtime env path. If RUNTIME_ENV_PATH is unset, fall back to
    per-signature default at data/agent_data/{SIGNATURE}/.runtime_env.json.
    """
    override = runtime_env_path_override()  # a tool call on behalf of a named agent (see tools/agent_context.py)
    if override:
        return override
    path = os.environ.get("RUNTIME_ENV_PATH")
    if not path:
        signature = os.environ.get("SIGNATURE")
        if signature:
            folder = agent_dir(signature)  # raises ValueError for a signature that is not a plain folder name
            # Ensure parent exists but do not create file here
            folder.mkdir(parents=True, exist_ok=True)
            path = str(folder / ".runtime_env.json")
            os.environ["RUNTIME_ENV_PATH"] = path
    return path or ""


def _load_runtime_env() -> dict:
    path = _resolve_runtime_env_path()
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def get_config_value(key: str, default=None):
    runtime_env = _load_runtime_env()
    if key in runtime_env:
        return runtime_env[key]
    return os.getenv(key, default)


def write_config_value(key: str, value: Any):
    """Store one value in the runtime settings file. The file is replaced atomically, so a process reading it at the same moment sees the old or the new
    contents, never half a file (which would read as "no settings")."""
    path = _resolve_runtime_env_path()
    if not path:
        print(f"⚠️  WARNING: RUNTIME_ENV_PATH not set, config value '{key}' not persisted")
        return
    runtime_env = _load_runtime_env()
    runtime_env[key] = value
    temporary = f"{path}.{os.getpid()}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(runtime_env, f, ensure_ascii=False, indent=4)
        os.replace(temporary, path)
    except OSError as e:
        print(f"❌ Error writing config to {path}: {e}")
        try:
            os.unlink(temporary)
        except OSError:
            pass


def extract_conversation(conversation: dict, output_type: str):
    """Extract information from a conversation payload.

    Args:
        conversation: A mapping that includes 'messages' (list of dicts or objects with attributes).
        output_type: 'final' to return the model's final answer content; 'all' to return the full messages list.

    Returns:
        For 'final': the final assistant content string if found, otherwise None.
        For 'all': the original messages list (or empty list if missing).
    """

    def get_field(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def get_nested(obj, path, default=None):
        current = obj
        for key in path:
            current = get_field(current, key, None)
            if current is None:
                return default
        return current

    messages = get_field(conversation, "messages", []) or []

    if output_type == "all":
        return messages

    if output_type == "final":
        # Prefer the last message with finish_reason == 'stop' and non-empty content.
        for msg in reversed(messages):
            finish_reason = get_nested(msg, ["response_metadata", "finish_reason"])
            content = get_field(msg, "content")
            if finish_reason == "stop" and isinstance(content, str) and content.strip():
                return content

        # Fallback: last AI-like message with non-empty content and not a tool call.
        for msg in reversed(messages):
            content = get_field(msg, "content")
            additional_kwargs = get_field(msg, "additional_kwargs", {}) or {}
            tool_calls = None
            if isinstance(additional_kwargs, dict):
                tool_calls = additional_kwargs.get("tool_calls")
            else:
                tool_calls = getattr(additional_kwargs, "tool_calls", None)

            is_tool_invoke = isinstance(tool_calls, list)
            # Tool messages often have 'tool_call_id' or 'name' (tool name)
            has_tool_call_id = get_field(msg, "tool_call_id") is not None
            tool_name = get_field(msg, "name")
            is_tool_message = has_tool_call_id or isinstance(tool_name, str)

            if not is_tool_invoke and not is_tool_message and isinstance(content, str) and content.strip():
                return content

        return None

    raise ValueError("output_type must be 'final' or 'all'")


def extract_tool_messages(conversation: dict):
    """Return all ToolMessage-like entries from the conversation.

    A ToolMessage is identified heuristically by having either:
      - a non-empty 'tool_call_id', or
      - a string 'name' (tool name) and no 'finish_reason' like normal AI messages

    Supports both dict-based and object-based messages.
    """

    def get_field(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def get_nested(obj, path, default=None):
        current = obj
        for key in path:
            current = get_field(current, key, None)
            if current is None:
                return default
        return current

    messages = get_field(conversation, "messages", []) or []
    tool_messages = []
    for msg in messages:
        tool_call_id = get_field(msg, "tool_call_id")
        name = get_field(msg, "name")
        finish_reason = get_nested(msg, ["response_metadata", "finish_reason"])  # present for AIMessage
        # Treat as ToolMessage if it carries a tool_call_id, or looks like a tool response
        if tool_call_id or (isinstance(name, str) and not finish_reason):
            tool_messages.append(msg)
    return tool_messages


def extract_first_tool_message_content(conversation: dict):
    """Return the content of the first ToolMessage if available, else None."""
    msgs = extract_tool_messages(conversation)
    if not msgs:
        return None

    first = msgs[0]
    if isinstance(first, dict):
        return first.get("content")
    return getattr(first, "content", None)

