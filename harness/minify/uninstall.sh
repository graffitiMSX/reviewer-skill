#!/usr/bin/env bash
# harness/minify/uninstall.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"

# Remove $1 only if it is a symlink resolving into $ROOT -- i.e. only if this
# harness put it there. Anything else (a real file, or a symlink elsewhere) is
# left alone, with a note on stderr.
unlink_if_ours() {
    local dest="$1" resolved
    if [ -L "$dest" ]; then
        resolved="$(readlink -f "$dest" 2>/dev/null || true)"
        case "$resolved" in
            "$ROOT"/*) rm -f "$dest"; return 0 ;;
        esac
    fi
    if [ -e "$dest" ] || [ -L "$dest" ]; then
        echo "uninstall.sh: leaving $dest in place — not a symlink into this harness ($ROOT)" >&2
    fi
}

unlink_if_ours "$CLAUDE_HOME/output-styles/minified.md"
unlink_if_ours "$BIN_DIR/minify-harness"
unlink_if_ours "$BIN_DIR/minread"
python3 -c "
import sys; sys.path.insert(0, '$ROOT/../..')
from harness.minify.lib.settings import unpatch, SettingsError
try:
    changed = unpatch('$CLAUDE_HOME/settings.json')
except SettingsError as e:
    print(f'uninstall.sh: {e}', file=sys.stderr)
    sys.exit(1)
print('unpatched:', changed or 'nothing')
"
echo "removed. logs kept at ~/.claude/minify-harness/ — delete them by hand if you want them gone."
