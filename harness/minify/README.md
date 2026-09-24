# minify harness

Emit code minified, format it back with the project's own formatter at turn end,
and measure what the minified emission saved.

    ./install.sh                  # symlinks + three hook entries in ~/.claude/settings.json
    /output-style minified        # arm it
    minify-harness doctor         # what is safe to minify in this project
    minify-harness report         # what it saved this session
    ./uninstall.sh                # reverse everything

A `SessionStart` hook cannot fire for the session that installed it, so after running
`install.sh` there is no verdict and no logger yet -- start a new session, or restart
Claude Code, for the hooks to take effect.

Design: `DESIGN.md`. Plan: `PLAN.md`.

The report counts emitted code only. A failed `Edit` against a formatted file costs a
re-read that the number does not net out, so treat it as "savings on emitted code",
not "savings on the session".

The formatter normalizes indentation and line breaks, but it is not a canonicalizer:
blank lines and brace style removed by minification do not come back. "Format it back"
means the code becomes syntactically well-formed and consistently styled again, not
that the original file is restored byte-for-byte.

Tests: `python3 -m unittest discover -s harness/minify/tests -t .` from the repo root.
Seven round-trip tests skip unless the project has a local prettier.

The harness lives in `harness/minify/` within this checkout. `install.sh` symlinks
into `~/.claude/` and writes hook commands into `~/.claude/settings.json` that embed
the **absolute path** to this checkout — so moving or renaming this directory breaks
the installed hooks. If you need to move it, run `./uninstall.sh` first, move the
directory, then run `./install.sh` again from its new location. (The plan's own
stated intent is to move this harness into its own repository once the tests pass,
so expect to do this once.)
