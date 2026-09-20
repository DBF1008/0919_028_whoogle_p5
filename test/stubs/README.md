# Offline dependency stubs

These stubs exist ONLY so the unit-test suite can run in offline
environments where the real packages cannot be installed. `test.sh`
prepends this directory to `PYTHONPATH` only for modules that are
missing from the active interpreter, so real installations always win.

Never import from `test/stubs` in application code.
