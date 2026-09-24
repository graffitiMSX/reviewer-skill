#!/usr/bin/env bash
# harness/minify/uninstall.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"

rm -f "$CLAUDE_HOME/output-styles/minified.md" "$BIN_DIR/minify-harness" "$BIN_DIR/minread"
python3 -c "
import sys; sys.path.insert(0, '$ROOT/../..')
from harness.minify.lib.settings import unpatch
print('unpatched:', unpatch('$CLAUDE_HOME/settings.json') or 'nothing')
"
echo "removed. logs kept at ~/.claude/minify-harness/ — delete them by hand if you want them gone."
