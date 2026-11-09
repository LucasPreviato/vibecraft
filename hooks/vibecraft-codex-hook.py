#!/usr/bin/env python3
"""Forward Codex lifecycle events to Vibecraft's loopback server."""

import json
import os
import sys
import time
import uuid
from urllib.error import URLError
from urllib.request import Request, urlopen


def record(value):
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    return {"text": value} if isinstance(value, str) else {"value": value}


def visual_tool_name(name):
    if name == "apply_patch":
        return "Edit"
    return name or "unknown"


def build_event(payload):
    hook_name = payload.get("hook_event_name")
    session_id = str(payload.get("session_id") or "codex-unknown")
    event_id = f"codex-{session_id}-{time.time_ns()}-{uuid.uuid4().hex[:8]}"
    event = {
        "id": event_id,
        "timestamp": int(time.time() * 1000),
        "provider": "codex",
        "sessionId": session_id,
        "cwd": str(payload.get("cwd") or ""),
    }

    if hook_name == "PreToolUse":
        event.update({
            "type": "pre_tool_use",
            "tool": visual_tool_name(payload.get("tool_name")),
            "toolInput": record(payload.get("tool_input")),
            "toolUseId": str(payload.get("tool_use_id") or event_id),
        })
    elif hook_name == "PostToolUse":
        response = record(payload.get("tool_response"))
        exit_code = response.get("exit_code")
        event.update({
            "type": "post_tool_use",
            "tool": visual_tool_name(payload.get("tool_name")),
            "toolInput": record(payload.get("tool_input")),
            "toolResponse": response,
            "toolUseId": str(payload.get("tool_use_id") or event_id),
            "success": response.get("success", exit_code in (None, 0)),
        })
    elif hook_name == "SubagentStart":
        agent_id = str(payload.get("agent_id") or event_id)
        event.update({
            "type": "pre_tool_use",
            "tool": "Task",
            "toolInput": {"description": str(payload.get("agent_type") or "Codex subagent")},
            "toolUseId": f"codex-agent-{agent_id}",
        })
    elif hook_name == "SubagentStop":
        agent_id = str(payload.get("agent_id") or event_id)
        response = payload.get("last_assistant_message")
        event.update({
            "type": "post_tool_use",
            "tool": "Task",
            "toolInput": {"description": str(payload.get("agent_type") or "Codex subagent")},
            "toolResponse": {"text": response} if response else {},
            "toolUseId": f"codex-agent-{agent_id}",
            "success": True,
        })
    elif hook_name == "Stop":
        event.update({
            "type": "stop",
            "stopHookActive": bool(payload.get("stop_hook_active", False)),
        })
        response = payload.get("last_assistant_message")
        if response:
            event["response"] = response
    elif hook_name == "SessionStart":
        event.update({"type": "session_start", "source": payload.get("source", "startup")})
    elif hook_name == "SessionEnd":
        event.update({"type": "session_end", "reason": payload.get("reason", "other")})
    elif hook_name == "UserPromptSubmit":
        event.update({"type": "user_prompt_submit", "prompt": str(payload.get("prompt") or "")})
    elif hook_name == "PreCompact":
        event.update({"type": "pre_compact", "trigger": payload.get("trigger", "auto")})
    elif hook_name == "PermissionRequest":
        tool = visual_tool_name(payload.get("tool_name"))
        event.update({
            "type": "notification",
            "message": f"Codex is requesting permission for {tool}",
            "notificationType": "permission_prompt",
        })
    else:
        return None

    return event


def main():
    payload = None
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return
        event = build_event(payload)
        if event is None:
            return

        port = os.environ.get("VIBECRAFT_PORT", "4003")
        request = Request(
            f"http://127.0.0.1:{port}/event",
            data=json.dumps(event, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=0.25):
            pass
    except (OSError, ValueError, TypeError, URLError):
        # Observability must never block or steer a Codex operation.
        pass
    finally:
        if isinstance(payload, dict) and payload.get("hook_event_name") in {"Stop", "SubagentStop"}:
            sys.stdout.write('{"continue":true}')


if __name__ == "__main__":
    main()
