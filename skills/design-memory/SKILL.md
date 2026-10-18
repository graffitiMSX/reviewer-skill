---
name: design-memory
description: Save or recall durable memory through the best memory system on this machine — ai-memory when it runs, else the claude-mem plugin, else Claude Code's MEMORY.md files. Use whenever the user says "remember", "note that", "save this decision", "what did we decide about", "what do we know about", asks to record an architectural or team decision so later sessions or other projects can find it, or when a pipeline stage ends with decisions a person approved (design-reconcile decisions, the action plan's decision log).
---

# Design Memory

One place for each memory, picked by tier so recall never has to search three systems that disagree. A script picks the tier; the SessionStart hook runs the same script, so the session usually already knows it.

```bash
python3 <this skill's directory>/scripts/memory_backend.py detect
```

| Tier | Recall | Write |
|---|---|---|
| `ai-memory` | its MCP search tools (find them with ToolSearch "ai-memory") | its MCP write tool, in the current project; preferences that should reach every project go to its cross-project profile |
| `claude-mem` | `mcp__plugin_claude-mem_mcp-search__*`, then MEMORY.md | MEMORY.md: claude-mem records sessions by itself and has no write tool |
| `memory-md` | MEMORY.md | MEMORY.md, as the system prompt describes |

When the chosen tier fails mid-session, use the next one and say which.

## Saving

1. **Check it belongs in memory.** A rule the team follows (a convention, a constraint every change must respect) belongs in the repo's `AGENTS.md`, `CLAUDE.md` or a decision record, where it is reviewed and always loaded; a memory system ranks and ages what it holds. Offer that instead, and save only a pointer. Never save secrets, credentials or excerpts of security findings.
2. **Write one fact per memory**, with why it holds and when it applies, the date, and the project it came from. A decision names who approved it and the alternatives turned down.
3. **Say where it went** (tier and page or file), so the user can find and correct it.

## Recalling

Search the active tier first and the lower tiers after it, since older memories may still sit there. Treat what comes back as what was true when it was written: check names, files and flags against the code before relying on them, and say when a memory is old or contradicted.

## Decisions across projects

A decision from one project reaches another only when it is tagged so a search finds it: add the topic (auth, queues, data store, consistency, deploy) and the kind of system it applies to. When starting work in a new project, search for decisions on the topics at hand and present them as precedent, not as rules: the new project's own `AGENTS.md` wins.
