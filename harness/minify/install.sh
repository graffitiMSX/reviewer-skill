#!/usr/bin/env bash
# harness/minify/install.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"

mkdir -p "$CLAUDE_HOME/output-styles" "$BIN_DIR"
ln -sf "$ROOT/output-styles/minified.md" "$CLAUDE_HOME/output-styles/minified.md"
ln -sf "$ROOT/bin/minify-harness" "$BIN_DIR/minify-harness"
ln -sf "$ROOT/bin/minread" "$BIN_DIR/minread"
python3 -c "
import sys; sys.path.insert(0, '$ROOT/../..')
from harness.minify.lib.settings import patch
print('patched:', patch('$CLAUDE_HOME/settings.json', '$ROOT') or 'nothing (already installed)')
"
echo "installed. activate with:  /output-style minified"
echo "check what is safe here:   minify-harness doctor"
