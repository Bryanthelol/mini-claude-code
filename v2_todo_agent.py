#!/usr/bin/env python3
"""
v2_todo_agent.py - Mini Claude Code: + Structured Planning (~300 lines)

Builds on v1 by adding the TodoWrite tool for explicit task tracking.
This solves the "context fade" problem: models forget their plan in long conversations.

New concepts:
- TodoManager: Validates and stores task list
- TodoWrite tool: Model updates tasks explicitly
- System reminders: Soft prompts to use todos

Usage:
    python v2_todo_agent.py
"""

import subprocess
import sys
from pathlib import Path

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("pip install anthropic")

# =============================================================================
# Configuration
# =============================================================================
API_KEY = "sk-xxx"  # Replace with your API key
BASE_URL = "https://api.moonshot.cn/anthropic"
MODEL = "claude-sonnet-4-20250514"
WORKDIR = Path.cwd()

client = Anthropic(api_key=API_KEY, base_url=BASE_URL) if BASE_URL else Anthropic(api_key=API_KEY)

# =============================================================================
# TodoManager - Structured task tracking
# =============================================================================
class TodoManager:
    """
    Manages a task list with constraints:
    - Max 20 items
    - Only one task can be in_progress at a time
    - Each task needs: content, status, activeForm
    """

    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        """Validate and update the todo list. Returns rendered view."""
        if not isinstance(items, list):
            raise ValueError("Items must be a list")

        validated = []
        in_progress_count = 0

        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"Item {i} must be an object")

            content = str(item.get("content", "")).strip()
            if not content:
                raise ValueError(f"Item {i}: content required")

            status = str(item.get("status", "pending")).lower()
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {i}: invalid status '{status}'")

            if status == "in_progress":
                in_progress_count += 1

            active_form = str(item.get("activeForm", "")).strip()
            if not active_form:
                raise ValueError(f"Item {i}: activeForm required")

            validated.append({
                "content": content,
                "status": status,
                "activeForm": active_form,
            })

        if len(validated) > 20:
            raise ValueError("Max 20 todos allowed")
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress")

        self.items = validated
        return self.render()

    def render(self) -> str:
        """Render todo list as text."""
        if not self.items:
            return "No todos."

        lines = []
        for item in self.items:
            if item["status"] == "completed":
                lines.append(f"[x] {item['content']}")
            elif item["status"] == "in_progress":
                lines.append(f"[>] {item['content']} <- {item['activeForm']}")
            else:
                lines.append(f"[ ] {item['content']}")

        completed = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({completed}/{len(self.items)} completed)")
        return "\n".join(lines)


TODO = TodoManager()

# =============================================================================
# System Prompt + Reminders
# =============================================================================
SYSTEM = f"""You are a coding agent at {WORKDIR}.

Loop: plan -> act with tools -> update todos -> report.

Rules:
- Use TodoWrite to track multi-step tasks
- Mark tasks in_progress before starting, completed when done
- Prefer tools over prose. Act, don't just explain.
- After finishing, summarize what changed."""

INITIAL_REMINDER = "<reminder>Use TodoWrite for multi-step tasks.</reminder>"
NAG_REMINDER = "<reminder>10+ turns without todo update. Please update todos.</reminder>"

# =============================================================================
# Tool Definitions (v1 tools + TodoWrite)
# =============================================================================
TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read file contents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace exact text in file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "TodoWrite",
        "description": "Update the task list. Use to plan and track progress.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "Task description"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                            "activeForm": {"type": "string", "description": "Present tense, e.g. 'Reading files'"},
                        },
                        "required": ["content", "status", "activeForm"],
                    },
                }
            },
            "required": ["items"],
        },
    },
]


# =============================================================================
# Tool Implementations
# =============================================================================
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(cmd: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot"]
    if any(d in cmd for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        result = subprocess.run(cmd, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=60)
        output = (result.stdout + result.stderr).strip()
        return output[:50000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout"
    except Exception as e:
        return f"Error: {e}"


def run_read(path: str, limit: int = None) -> str:
    try:
        text = safe_path(path).read_text()
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(text.splitlines()) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def run_todo(items: list) -> str:
    try:
        return TODO.update(items)
    except Exception as e:
        return f"Error: {e}"


def execute_tool(name: str, input: dict) -> str:
    if name == "bash":
        return run_bash(input["command"])
    elif name == "read_file":
        return run_read(input["path"], input.get("limit"))
    elif name == "write_file":
        return run_write(input["path"], input["content"])
    elif name == "edit_file":
        return run_edit(input["path"], input["old_text"], input["new_text"])
    elif name == "TodoWrite":
        return run_todo(input["items"])
    return f"Unknown tool: {name}"


# =============================================================================
# Agent Loop (with todo tracking)
# =============================================================================
rounds_without_todo = 0


def agent_loop(messages: list) -> list:
    global rounds_without_todo

    while True:
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )

        tool_calls = []
        for block in response.content:
            if hasattr(block, "text"):
                print(block.text)
            if block.type == "tool_use":
                tool_calls.append(block)

        if response.stop_reason != "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            return messages

        results = []
        used_todo = False

        for tc in tool_calls:
            print(f"\n> {tc.name}")
            output = execute_tool(tc.name, tc.input)
            print(f"  {output[:300]}{'...' if len(output) > 300 else ''}")
            results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": output,
            })
            if tc.name == "TodoWrite":
                used_todo = True

        if used_todo:
            rounds_without_todo = 0
        else:
            rounds_without_todo += 1

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": results})


# =============================================================================
# Main REPL
# =============================================================================
def main():
    global rounds_without_todo

    print(f"Mini Claude Code v2 (with Todos) - {WORKDIR}")
    print("Type 'exit' to quit.\n")

    history = []
    first_message = True

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input or user_input.lower() in ("exit", "quit", "q"):
            break

        # Build message content with optional reminders
        content = []

        # Initial reminder on first message
        if first_message:
            content.append({"type": "text", "text": INITIAL_REMINDER})
            first_message = False
        # Nag reminder if too many turns without todo
        elif rounds_without_todo > 10:
            content.append({"type": "text", "text": NAG_REMINDER})

        content.append({"type": "text", "text": user_input})
        history.append({"role": "user", "content": content})

        try:
            agent_loop(history)
        except Exception as e:
            print(f"Error: {e}")

        print()


if __name__ == "__main__":
    main()
