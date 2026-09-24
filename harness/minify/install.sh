#!/usr/bin/env bash
# harness/minify/install.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"

# Link $1 (a path under $ROOT) to $2, refusing to clobber anything this harness did
# not put there: a real file/directory, or a symlink pointing outside $ROOT.
link_into_harness() {
    local src="$1" dest="$2" resolved
    if [ -L "$dest" ]; then
        resolved="$(readlink -f "$dest" 2>/dev/null || true)"
        case "$resolved" in
            "$ROOT"/*) ln -sf "$src" "$dest"; return 0 ;;
        esac
        echo "install.sh: refusing to replace $dest — it is a symlink to $resolved, not into this harness ($ROOT)" >&2
        exit 1
    elif [ -e "$dest" ]; then
        echo "install.sh: refusing to replace $dest — a real file is already there" >&2
        exit 1
    fi
    ln -s "$src" "$dest"
}

mkdir -p "$CLAUDE_HOME/output-styles" "$BIN_DIR"
link_into_harness "$ROOT/output-styles/minified.md" "$CLAUDE_HOME/output-styles/minified.md"
link_into_harness "$ROOT/bin/minify-harness" "$BIN_DIR/minify-harness"
link_into_harness "$ROOT/bin/minread" "$BIN_DIR/minread"
python3 -c "
import sys; sys.path.insert(0, '$ROOT/../..')
from harness.minify.lib.settings import patch, SettingsError
try:
    changed = patch('$CLAUDE_HOME/settings.json', '$ROOT')
except SettingsError as e:
    print(f'install.sh: {e}', file=sys.stderr)
    sys.exit(1)
print('patched:', changed or 'nothing (already installed)')
"
echo "installed. activate with:  /output-style minified"
echo "check what is safe here:   minify-harness doctor"
