#!/bin/sh
# test.sh -- run every unit test script individually and report results.
#
# Usage:
#   ./test.sh                 run all test/test_*.py files one by one
#   ./test.sh test_tor.py     run only the named test file(s)
#   PYTHON_BIN=/path/python ./test.sh
#
# If third-party packages are missing from the interpreter (offline
# environment), minimal stubs from test/stubs are added to PYTHONPATH
# automatically. Real installations always take precedence.

set -u

SCRIPT_DIR="$(CDPATH= command cd -- "$(dirname -- "$0")" && pwd -P)"
cd "$SCRIPT_DIR"

# ---------------------------------------------------------------------------
# Pick a Python interpreter that has pytest available
# ---------------------------------------------------------------------------
pick_python() {
    if [ -n "${PYTHON_BIN:-}" ]; then
        echo "$PYTHON_BIN"
        return
    fi
    for candidate in python3 /opt/homebrew/bin/python3.10 /opt/homebrew/bin/python3; do
        if command -v "$candidate" >/dev/null 2>&1 && \
           "$candidate" -c "import pytest" >/dev/null 2>&1; then
            command -v "$candidate"
            return
        fi
    done
    echo "ERROR: no python interpreter with pytest found" >&2
    exit 1
}

# Avoid interference from unrelated globally installed pytest plugins
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

PYTHON="$(pick_python)"
echo "Using interpreter: $PYTHON"

# ---------------------------------------------------------------------------
# Enable stubs only for packages the interpreter is missing
# ---------------------------------------------------------------------------
REQUIRED="cachetools stem defusedxml cssutils validators waitress brotli dotenv"
MISSING=""
for mod in $REQUIRED; do
    if ! "$PYTHON" -c "import $mod" >/dev/null 2>&1; then
        MISSING="$MISSING $mod"
    fi
done

if [ -n "$MISSING" ]; then
    echo "Missing packages (using test/stubs):$MISSING"
    export PYTHONPATH="$SCRIPT_DIR/test/stubs${PYTHONPATH:+:$PYTHONPATH}"
fi

# httpx requires the optional 'h2' package for HTTP/2; fall back to HTTP/1.1
# when it is not installed (the app honors WHOOGLE_DISABLE_HTTP2).
if ! "$PYTHON" -c "import h2" >/dev/null 2>&1; then
    echo "Package h2 not installed: forcing WHOOGLE_DISABLE_HTTP2=1"
    export WHOOGLE_DISABLE_HTTP2=1
fi

# ---------------------------------------------------------------------------
# Collect the test scripts to run
# ---------------------------------------------------------------------------
if [ $# -gt 0 ]; then
    TEST_FILES=""
    for name in "$@"; do
        case "$name" in
            test/*) TEST_FILES="$TEST_FILES $name" ;;
            *)      TEST_FILES="$TEST_FILES test/$name" ;;
        esac
    done
else
    TEST_FILES=$(ls test/test_*.py 2>/dev/null)
fi

if [ -z "$TEST_FILES" ]; then
    echo "No test files found."
    exit 1
fi

# ---------------------------------------------------------------------------
# Run each unit test script individually
# ---------------------------------------------------------------------------
PASSED=0
FAILED=0
FAILED_FILES=""

for test_file in $TEST_FILES; do
    echo "================================================================"
    echo ">>> Running $test_file"
    echo "================================================================"
    if "$PYTHON" -m pytest "$test_file" -v; then
        PASSED=$((PASSED + 1))
    else
        FAILED=$((FAILED + 1))
        FAILED_FILES="$FAILED_FILES $test_file"
    fi
done

echo "================================================================"
echo "Summary: $PASSED file(s) passed, $FAILED file(s) failed"
if [ -n "$FAILED_FILES" ]; then
    echo "Failed:$FAILED_FILES"
fi
echo "================================================================"

[ "$FAILED" -eq 0 ]
