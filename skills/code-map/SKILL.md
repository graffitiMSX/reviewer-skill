---
name: code-map
description: Map a repository as a graph before analysing it — files and imports, functions and calls, every route with its middleware, handler and tables, background jobs, which code reads and writes each table, client routes and API calls — and write it as a queryable file plus short markdown views that the review, planning and fix skills read instead of rediscovering the structure by grep. Use whenever the user asks to map, index or graph the code, wants a dependency graph, call graph, route inventory, "what depends on this file", "which routes touch this table", "where is this table written", import cycles, or is about to start a design review, re-review or action plan on a repo that has no map yet or whose map is stale. Stage 0 of the remediation pipeline (code-map → design-review → action-plan → plan-to-issues → dispatch-fixes → design-rereview).
---

# Code Map

Stage 0 of the remediation pipeline, and useful alone. Every reviewer starts by working out the same things: where the entry points are, what guards them, what they reach, who owns each table. Done by grep, five reviewers do it five times and each sees a different part. This skill does it once, mechanically, and writes `docs/remediation/code-map/` in the target repo:

| File | Holds |
|---|---|
| `code-map.md` | the index: counts, the commit it was built from, how to query, how far to trust it |
| `modules.md` | most depended-on files, import cycles, folders that depend on each other both ways, external packages |
| `entry-points.md` | every route with its middleware in running order, handler and tables reached; jobs, queues and schedules |
| `data.md` | readers and writers of each table; tables written from more than one folder |
| `frontend.md` | client routes, API call sites, and client calls and server routes that do not match up |
| `graph.json` | the graph itself, read by the query commands |

The whole map is computed by `scripts/codemap.py`. There is no judgement in it, so there is no agent: your part is to run it, check that it saw the system, and say what it could not see.

## Steps

1. **Pick the target.** Repo root, and the branch the team ships from when the checkout is on something else; say which commit is being mapped. Default output is `docs/remediation/code-map/` in that repo.
2. **Check for an existing map.**
   ```bash
   python3 <this skill's directory>/scripts/codemap.py status <repo>
   ```
   `fresh` means there is nothing to do unless the user wants a rebuild. `stale` and `missing` mean build.
3. **Build.**
   ```bash
   python3 <this skill's directory>/scripts/codemap.py build <repo>
   ```
   It uses `cgr` (code-graph-rag) when it is installed, which adds functions, methods, classes and call edges for every language cgr parses, and takes a few minutes on a large repo. Without cgr it falls back to a builtin engine that needs nothing installed and covers imports, routes, jobs and tables for TypeScript, JavaScript and Python in seconds, at file level. The first line of output says which engine ran and why. Force one with `--engine cgr` or `--engine builtin`.

   The script indexes a temporary copy of the working tree, so it leaves nothing in the repo except the output folder, and it does not touch the user's own cgr database or cache.
4. **Check that it saw the system.** The script cannot know what it missed, so compare its counts with the repo:
   - Routes: count route declarations with a quick grep in the folder that holds them and compare with the map. A large gap means a framework or registration style the scanner does not know.
   - Tables: compare with the migrations or the schema file.
   - Engine: if cgr was expected and the builtin ran, read the reason in the output.
   - Open two or three rows of `entry-points.md` against the code: middleware order, handler, a table.

   Report gaps plainly in your summary; do not patch the generated files by hand, because the next build would lose the edit. If a whole framework is missing, say so: the reviewers then know to map that part themselves.
5. **Present** the counts, then what stands out without needing interpretation: import cycles, folders that depend on each other in both directions, tables written from several folders, routes with no router-level or inline middleware, client calls with no server route. These are leads for the reviewers, not findings; say so. Then offer `/design-review`, which picks the map up.

Whether to commit the folder is the team's call. The markdown views are small and read well in a pull request; `graph.json` can reach a few megabytes and is rebuilt from the code at any time.

## How the other skills use it

They read the map when it is there and work as before when it is not. The rule they follow is in `../design-review/references/conventions.md` under "Code map": read the view for your lens first, query instead of grepping for structure, and open the code before citing anything, because the map points at evidence and is not evidence. A stale map is still useful for the files that did not change; `status` says how many did.

Query commands, all taking the map folder:

```bash
codemap.py impact <map> <file>     # everything that depends on the file, and the routes that reach it
codemap.py route  <map> <text>     # matching routes: middleware, handler, tables
codemap.py table  <map> <name>     # every read and write site with its line and enclosing function
codemap.py deps|rdeps <map> <file> [--depth N]
codemap.py symbol|callers|callees <map> <name> [--depth N]    # cgr engine only
```

## What it cannot see

Say these when presenting, so nobody reads an absence as proof:

- It matches patterns in source text. Routes registered in a loop or from a table, SQL assembled from fragments or written with lowercase keywords, and dynamic imports are missed.
- A route's tables come from call edges when they resolve. Behind dependency injection or an inline handler they do not, and the cell falls back to what the handler's file and its imports touch, marked `≈`.
- Call edges between files that do not import each other are dropped, which removes name collisions and, with them, calls made through an interface.
- Route scanning knows Express-style routers, NestJS decorators, and Flask and FastAPI decorators. Table scanning knows SQL text, knex-style builders, Prisma calls and the common schema declarations.

## Human artifacts

Follow "Human artifacts" in `../design-review/references/conventions.md`; it is part of the stage, not an extra. Keep the run record in `docs/remediation/work/code-map/`: `run.md`, plus `build.txt` (the build command's output) and `verification.md` (the route and table counts you compared, and the rows you checked against the code). When the gate passes, render the page with `page.py code-map docs/remediation`, tell the user where it is, and ask whether to publish it.

## Quality gate

- `codemap.py build` exited zero and `codemap.py status <repo>` says `fresh`.
- The route and table counts were compared with the repo, and any gap is stated.
- The summary names the engine, the commit, and what the map could not see in this repo.
- Nothing in the output folder was edited by hand.
- The run record exists in `docs/remediation/work/code-map/` and `pages/code-map.html` was rendered from the final artifact.
