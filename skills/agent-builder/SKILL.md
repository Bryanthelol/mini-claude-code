---
name: agent-builder
description: Build AI coding agents from scratch. Use when asked to create an agent, implement agent features, or understand agent architecture.
---

# Agent Builder Skill

You are now an expert in building AI coding agents. This skill teaches you the complete architecture and implementation patterns for creating agents like Claude Code, Cursor Agent, and Codex CLI.

## Core Philosophy

> **The Model IS the Agent. Code just runs the loop.**

Strip away all complexity and you find: a loop that lets the model call tools until the task is done.

```
Traditional: User -> Model -> Response
Agent:       User -> Model -> [Tool -> Result]* -> Response
                                   ^________|
```

The asterisk (*) is everything. The model calls tools REPEATEDLY until it decides to stop.

## The Universal Agent Loop

Every coding agent shares this pattern:

```python
def agent_loop(messages: list) -> list:
    while True:
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )

        # Collect tool calls
        tool_calls = [b for b in response.content if b.type == "tool_use"]

        # If no tools called, task complete
        if response.stop_reason != "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            return messages

        # Execute tools and collect results
        results = []
        for tc in tool_calls:
            output = execute_tool(tc.name, tc.input)
            results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": output
            })

        # Append and continue
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": results})
```

This is the ENTIRE agent. Everything else is refinement.

## Progressive Complexity Levels

Build agents incrementally. Each level adds ONE concept:

### Level 0: Bash is All You Need (~50 lines)

**Insight**: One tool (bash) can do everything.

```python
TOOL = [{
    "name": "bash",
    "description": "Execute shell command. Read: cat/grep/find. Write: echo > file. Subagent: python agent.py 'task'",
    "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}
}]
```

Key patterns:
- Read files: `cat`, `grep`, `find`, `ls`
- Write files: `echo 'content' > file`, `cat << 'EOF' > file`
- **Subagent**: `python agent.py "subtask"` (self-call = context isolation)

### Level 1: Four Essential Tools (~200 lines)

**Insight**: 4 tools cover 90% of coding tasks.

| Tool | Purpose | When to use |
|------|---------|-------------|
| `bash` | Run commands | git, npm, python, any CLI |
| `read_file` | Read contents | Understanding code |
| `write_file` | Create/overwrite | New files |
| `edit_file` | Surgical changes | Precise modifications |

```python
def edit_file(path, old_text, new_text):
    content = Path(path).read_text()
    if old_text not in content:
        return "Error: Text not found"
    return content.replace(old_text, new_text, 1)  # First occurrence only
```

### Level 2: Structured Planning (~300 lines)

**Problem**: Model forgets plan after many tool calls ("context fade").

**Solution**: TodoWrite tool makes plans visible.

```python
class TodoManager:
    def __init__(self):
        self.items = []  # Max 20

    def update(self, items):
        # Constraints:
        # - Only ONE item can be in_progress
        # - Each needs: content, status, activeForm
        # - Status: pending | in_progress | completed
```

Display format:
```
[x] Completed task
[>] In progress task <- Doing something...
[ ] Pending task

(1/3 completed)
```

**Key insight**: Constraints enable, not limit. "One in_progress" forces focus.

### Level 3: Subagent Mechanism (~450 lines)

**Problem**: Context pollution - exploration details fill the context.

**Solution**: Task tool spawns isolated child agents.

```python
AGENT_TYPES = {
    "explore": {
        "tools": ["bash", "read_file"],  # Read-only
        "prompt": "Search and analyze. Never modify. Return concise summary."
    },
    "code": {
        "tools": "*",  # All tools
        "prompt": "Implement changes efficiently."
    },
    "plan": {
        "tools": ["bash", "read_file"],
        "prompt": "Output numbered plan. Don't change files."
    }
}

def run_task(description, prompt, agent_type):
    config = AGENT_TYPES[agent_type]

    # KEY: Fresh message history (isolated context)
    sub_messages = [{"role": "user", "content": prompt}]
    sub_tools = filter_tools(config["tools"])

    # Run same loop, return only final text
    while True:
        response = client.messages.create(...)
        if response.stop_reason != "tool_use":
            return extract_final_text(response)
        # Execute tools...
```

### Level 4: Skills Mechanism (~550 lines)

**Problem**: Model doesn't know domain-specific HOW-TOs.

**Solution**: Skills = knowledge packages loaded on-demand.

```
skills/
├── pdf/
│   └── SKILL.md          # YAML frontmatter + instructions
├── mcp-builder/
│   ├── SKILL.md
│   └── references/       # Additional docs
```

SKILL.md format:
```markdown
---
name: pdf
description: Process PDF files
---

# PDF Processing

Use pdftotext for extraction:
\`\`\`bash
pdftotext input.pdf -
\`\`\`
```

**Critical**: Inject skills as tool_result (user message), NOT system prompt.
- System prompt changes = cache invalidated = 20-50x cost
- Tool result appends = prefix unchanged = cache hit

## System Prompt Template

```python
SYSTEM = f"""You are a coding agent at {WORKDIR}.

Loop: think briefly -> use tools -> report results.

Rules:
- Prefer tools over prose. Act, don't just explain.
- Never invent file paths. Use ls/find first if unsure.
- Make minimal changes. Don't over-engineer.
- After finishing, summarize what changed."""
```

## Tool Definition Template

```python
{
    "name": "tool_name",
    "description": "What it does. When to use it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "param1": {
                "type": "string",
                "description": "What this parameter is for"
            }
        },
        "required": ["param1"]
    }
}
```

## Safety Patterns

```python
def safe_path(p: str) -> Path:
    """Prevent path escape attacks."""
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(cmd: str) -> str:
    """Block dangerous commands."""
    dangerous = ["rm -rf /", "sudo", "shutdown", "> /dev/"]
    if any(d in cmd for d in dangerous):
        return "Error: Dangerous command blocked"

    result = subprocess.run(
        cmd, shell=True, cwd=WORKDIR,
        capture_output=True, text=True,
        timeout=60  # Prevent hanging
    )
    return (result.stdout + result.stderr)[:50000]  # Truncate
```

## Complete Minimal Agent

Here's a complete working agent in ~100 lines:

```python
#!/usr/bin/env python3
from anthropic import Anthropic
from pathlib import Path
import subprocess, os

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = "claude-sonnet-4-20250514"
WORKDIR = Path.cwd()

SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to complete tasks."

TOOLS = [
    {"name": "bash", "description": "Run shell command",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write file",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
]

def execute(name, args):
    if name == "bash":
        r = subprocess.run(args["command"], shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=60)
        return (r.stdout + r.stderr) or "(empty)"
    if name == "read_file":
        return (WORKDIR / args["path"]).read_text()
    if name == "write_file":
        p = WORKDIR / args["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args["content"])
        return f"Wrote {len(args['content'])} bytes"

def agent(prompt, history=[]):
    history.append({"role": "user", "content": prompt})
    while True:
        r = client.messages.create(model=MODEL, system=SYSTEM, messages=history, tools=TOOLS, max_tokens=8000)
        history.append({"role": "assistant", "content": r.content})
        if r.stop_reason != "tool_use":
            return "".join(b.text for b in r.content if hasattr(b, "text"))
        results = [{"type": "tool_result", "tool_use_id": b.id, "content": execute(b.name, b.input)}
                   for b in r.content if b.type == "tool_use"]
        history.append({"role": "user", "content": results})

if __name__ == "__main__":
    h = []
    while (q := input(">> ")) not in ("q", ""):
        print(agent(q, h))
```

## Design Principles

1. **Model controls the loop** - Code just executes, model decides
2. **Tools are capabilities** - What the model CAN do
3. **Skills are knowledge** - What the model KNOWS how to do
4. **Constraints enable** - Max items, one in_progress = focus
5. **Context is precious** - Isolate subtasks, truncate outputs
6. **Cache is money** - Append-only messages, fixed system prompt

## When Building a New Agent

1. Start with Level 1 (4 tools + loop)
2. Add TodoWrite if tasks are complex
3. Add subagents if context gets polluted
4. Add skills for domain expertise
5. Never over-engineer the first version

## Anti-Patterns to Avoid

| Anti-Pattern | Problem | Solution |
|--------------|---------|----------|
| Dynamic system prompt | Cache miss every call | Fixed prompt, state in messages |
| Message editing | Invalidates cache | Append-only |
| Too many tools | Model gets confused | Start with 4, add as needed |
| No output truncation | Context overflow | Limit to 50KB per result |
| No timeout | Hanging commands | 60s default timeout |

Now go build agents!
