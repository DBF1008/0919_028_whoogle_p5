# Test stubs

Minimal stand-ins for third-party packages that are unavailable in the
offline development environment. `test.sh` only prepends this directory to
`PYTHONPATH` when the real package cannot be imported, so production and CI
always use the real dependencies.

Stubbed packages: `cachetools`, `stem`, `defusedxml`, `cssutils`,
`validators`, `waitress`, `brotli`, `dotenv`.
