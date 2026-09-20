#!/bin/sh
# Manual unit-test runner for whoogle-search.
#
# Usage:
#   ./test.sh                              # run the whole unit-test suite
#   ./test.sh test/test_connection_manager.py   # run a single test file
#   ./test.sh -k tor                       # forward extra args to pytest
#
# The script mirrors the static-file setup of './run test' and falls
# back to the offline stubs under test/stubs for any dependency that is
# missing from the active interpreter (stem, cachetools, dotenv,
# cssutils, waitress, validators, ...). Real installations always win.

set -e

SCRIPT_DIR="$(CDPATH= command cd -- "$(dirname -- "$0")" && pwd -P)"
cd "$SCRIPT_DIR"

# ---------------------------------------------------------------------------
# Pick a Python interpreter that has the app dependencies installed.
# ---------------------------------------------------------------------------
PYBIN=""
if python3 -c "import flask, httpx" >/dev/null 2>&1; then
    PYBIN="python3"
elif command -v pytest >/dev/null 2>&1; then
    # Reuse the interpreter that the pytest entry point runs with
    PYBIN=$(head -1 "$(command -v pytest)" | sed 's/^#!//')
fi

if [ -z "$PYBIN" ] || [ ! -x "$(command -v "$PYBIN" 2>/dev/null || echo "$PYBIN")" ]; then
    echo "error: no Python interpreter with flask/httpx found" >&2
    exit 1
fi

echo "Using interpreter: $PYBIN"

# ---------------------------------------------------------------------------
# Static-file setup (same as './run test')
# ---------------------------------------------------------------------------
export APP_ROOT="$SCRIPT_DIR/test"
export STATIC_FOLDER="$APP_ROOT/static"
rm -rf "$STATIC_FOLDER"
ln -s "$SCRIPT_DIR/app/static" "$STATIC_FOLDER"

# Seed a minimal offline bangs database if none was downloaded yet.
# The app fetches the full DDG bang list from the network on first run;
# the bang unit tests only need a handful of well-known entries.
BANG_FILE="$SCRIPT_DIR/app/static/bangs/bangs.json"
if [ ! -f "$BANG_FILE" ] || [ "$(wc -c < "$BANG_FILE")" -le 4 ]; then
    mkdir -p "$(dirname "$BANG_FILE")"
    cp "$SCRIPT_DIR/test/bangs_seed.json" "$BANG_FILE"
    echo "Seeded offline bangs database: $BANG_FILE"
fi

# ---------------------------------------------------------------------------
# Inject offline stubs only for modules the interpreter is missing
# ---------------------------------------------------------------------------
PYTHONPATH="$SCRIPT_DIR"
STUBS_USED=""
for mod in stem cachetools dotenv cssutils waitress validators; do
    if ! "$PYBIN" -c "import $mod" >/dev/null 2>&1; then
        STUBS_USED="$STUBS_USED $mod"
    fi
done
if [ -n "$STUBS_USED" ]; then
    PYTHONPATH="$SCRIPT_DIR/test/stubs:$PYTHONPATH"
    echo "Using offline stubs for:$STUBS_USED"
fi
export PYTHONPATH

# ---------------------------------------------------------------------------
# Run the unit tests
# ---------------------------------------------------------------------------
if [ $# -eq 0 ]; then
    set -- test
fi
exec "$PYBIN" -m pytest -sv "$@"
