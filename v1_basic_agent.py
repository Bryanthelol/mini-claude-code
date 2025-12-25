#!/usr/bin/env python3
"""
v1_basic_agent.py - Mini Claude Code: Core Agent Loop (~200 lines)

The simplest possible coding agent: 4 tools + a loop.
This is the essence of Claude Code, Cursor Agent, Codex CLI, etc.

Key insight: The model is the agent. Code just runs the loop.

Usage:
    python v1_basic_agent.py
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
BASE_URL = "https://api.moonshot.cn/anthropic"  # Or use Anthropic directly
MODEL = "claude-sonnet-4-20250514"
WORKDIR = Path.cwd()

# =============================================================================
# Client Setup
# =============================================================================
client = Anthropic(api_key=API_KEY, base_url=BASE_URL) if BASE_URL else Anthropic(api_key=API_KEY)

# =============================================================================
# System Prompt - The only "configuration" the model needs
# =============================================================================
SYSTEM = f"""You are a coding agent at {WORKDIR}.

Loop: think briefly -> use tools -> report results.

Rules:
- Prefer tools over prose. Act, don't just explain.
- Never invent file paths. Use bash ls/find first if unsure.
- Make minimal changes. Don't over-engineer.
- After finishing, summarize what changed."""

# =============================================================================
# Tool Definitions - 4 tools cover 90% of coding tasks
# =============================================================================
TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command. Use for: ls, find, grep, git, npm, python, etc.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read file contents. Returns UTF-8 text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer", "description": "Max lines (default: all)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates parent directories if needed.",
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
        "description": "Replace exact text in a file. Use for surgical edits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string", "description": "Exact text to find"},
                "new_text": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
]


# =============================================================================
# Tool Implementations
# =============================================================================
def safe_path(p: str) -> Path:
    """Ensure path stays within workspace."""
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(cmd: str) -> str:
    """Execute shell command with safety checks."""
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in cmd for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=60
        )
        output = (result.stdout + result.stderr).strip()
        return output[:50000] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out (60s)"
    except Exception as e:
        return f"Error: {e}"


def run_read(path: str, limit: int = None) -> str:
    """Read file contents."""
    try:
        text = safe_path(path).read_text()
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit]
            lines.append(f"... ({len(text.splitlines()) - limit} more lines)")
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    """Write content to file."""
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    """Replace exact text in file."""
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        new_content = content.replace(old_text, new_text, 1)
        fp.write_text(new_content)
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def execute_tool(name: str, input: dict) -> str:
    """Dispatch tool call to implementation."""
    if name == "bash":
        return run_bash(input["command"])
    elif name == "read_file":
        return run_read(input["path"], input.get("limit"))
    elif name == "write_file":
        return run_write(input["path"], input["content"])
    elif name == "edit_file":
        return run_edit(input["path"], input["old_text"], input["new_text"])
    return f"Unknown tool: {name}"


# =============================================================================
# The Agent Loop - This is the core of everything
# =============================================================================
def agent_loop(messages: list) -> list:
    """
    The complete agent in one function:
    1. Send messages to model
    2. If model returns text only -> done
    3. If model calls tools -> execute and continue
    """
    while True:
        # Call the model
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )

        # Collect tool calls
        tool_calls = []
        for block in response.content:
            if hasattr(block, "text"):
                print(block.text)
            if block.type == "tool_use":
                tool_calls.append(block)

        # If no tool calls, we're done
        if response.stop_reason != "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            return messages

        # Execute tools and continue
        results = []
        for tc in tool_calls:
            print(f"\n> {tc.name}: {tc.input}")
            output = execute_tool(tc.name, tc.input)
            print(f"  {output[:200]}{'...' if len(output) > 200 else ''}")
            results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": output,
            })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": results})


# =============================================================================
# Main REPL
# =============================================================================
def main():
    print(f"Mini Claude Code v1 - {WORKDIR}")
    print("Type 'exit' to quit.\n")

    history = []
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input or user_input.lower() in ("exit", "quit", "q"):
            break

        history.append({"role": "user", "content": user_input})

        try:
            agent_loop(history)
        except Exception as e:
            print(f"Error: {e}")

        print()


if __name__ == "__main__":
    main()
