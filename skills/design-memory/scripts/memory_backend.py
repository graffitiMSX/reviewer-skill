#!/usr/bin/env python3
"""Pick the memory backend for this machine, highest tier first.

Usage:
  memory_backend.py detect     one line: the backend, then why
  memory_backend.py hook       SessionStart hook: the same, phrased as context
                               for the session, plus a warning when two
                               capture systems run at once

Tiers, first available wins:
  ai-memory   the `ai-memory` command exists and `ai-memory status` exits 0
  claude-mem  the claude-mem plugin is enabled in ~/.claude/settings.json
  memory-md   Claude Code's own MEMORY.md files, always available

claude-mem has search tools but no tool for writing, so under it recall goes
through claude-mem and deliberate writes go to MEMORY.md. ai-memory has both.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

SETTINGS = Path.home() / ".claude" / "settings.json"


def ai_memory():
    if not shutil.which("ai-memory"):
        return False, "the ai-memory command is not installed"
    try:
        done = subprocess.run(["ai-memory", "status"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"`ai-memory status` failed ({exc.__class__.__name__})"
    if done.returncode != 0:
        return False, f"`ai-memory status` exited {done.returncode}, so its server is not answering"
    return True, "`ai-memory status` exited 0"


def claude_mem():
    try:
        plugins = json.loads(SETTINGS.read_text(encoding="utf-8")).get("enabledPlugins", {})
    except (OSError, ValueError):
        return False, f"could not read {SETTINGS}"
    on = [name for name, enabled in plugins.items() if name.split("@")[0] == "claude-mem" and enabled]
    if on:
        return True, f"plugin {on[0]} is enabled"
    return False, "the claude-mem plugin is not enabled"


def detect():
    has_ai, why_ai = ai_memory()
    has_cm, why_cm = claude_mem()
    if has_ai:
        return "ai-memory", why_ai, has_cm
    if has_cm:
        return "claude-mem", f"{why_cm}; ai-memory skipped: {why_ai}", False
    return "memory-md", f"ai-memory skipped: {why_ai}; claude-mem skipped: {why_cm}", False


HOW = {
    "ai-memory": "Recall and write through the ai-memory MCP tools (find them with ToolSearch \"ai-memory\"). "
                 "MEMORY.md keeps only a pointer to ai-memory and the few facts every session must load.",
    "claude-mem": "Recall through the claude-mem search tools (mcp__plugin_claude-mem_mcp-search__*) before MEMORY.md. "
                  "claude-mem records sessions by itself and has no write tool, so deliberate memories go to MEMORY.md.",
    "memory-md": "Recall and write with the MEMORY.md files described in the system prompt.",
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("detect", "hook"):
        sys.exit(__doc__)
    backend, why, both = detect()
    if sys.argv[1] == "detect":
        print(f"{backend}: {why}")
        return
    print(f"Memory backend for this session: {backend} ({why}). {HOW[backend]} "
          "If it fails mid-session, fall back to the next tier (ai-memory, claude-mem, MEMORY.md) and say so.")
    if both:
        print("Warning: ai-memory and the claude-mem plugin are both capturing sessions, so their histories will diverge. "
              "Tell the user once; disabling claude-mem is their call.")


if __name__ == "__main__":
    main()
