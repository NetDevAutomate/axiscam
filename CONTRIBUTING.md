# Contributing

## Setup

```bash
uv sync --all-extras
uv run pre-commit install
```

## The gate

Every commit runs the same checks locally (pre-commit) and in CI
(`.github/workflows/ci.yml`, mirroring the `python-uv` profile of the central
`ci-standards` tool):

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
uv run pytest -q --cov=src/axis_cam        # fail_under is in pyproject.toml; ratchet it, never lower it
```

A gate you have never watched fail is not a gate: when you add or change a check,
make it fail once on purpose before trusting the green.

## Conventions

- **Contracts come from the VAPIX documentation on the day, not from memory.**
  Say in the commit message which page you read. A test that mirrors an
  assumption instead of the documented contract certifies the bug (see
  `ParamAPI` in the changelog).
- **"Cannot read" is not "disabled".** Catch `AxisDeviceError` /
  `AxisApiNotSupportedError` where a device genuinely may lack an API; let
  `AxisAuthenticationError` and `AxisConnectionError` propagate.
- **Adding an API module:** `api/<module>.py` with `@register`, `name`, `api_id`
  and `read()` if it is a resource; import it in `api/__init__.py`; one typed
  declaration on `AxisDevice`. `tests/test_registry.py` and `tests/test_docs.py`
  tell you what you forgot.
- **Writing to a device** goes through `cli/confirm.py`: read current state, show
  the plan, `--dry-run` stops, confirm (`--yes` skips), apply, re-read and verify.
  Secrets travel in a POST body, never a URL, and never in `argv`.
- **Anything written to disk** that describes a device uses
  `axis_cam.files.write_private` (`0600`).
- Docstrings in Google style; `ruff` enforces them. Type hints everywhere.

## Verifying against a real device

The unit suite cannot validate a device contract. Before merging a change to a
module's request or parse logic, run the relevant read-only command against a
device and record the firmware version in the PR.
