# ADR 0004: Modular Package Layout and Offline Agent-Friendly Tooling

- **Status:** Accepted
- **Date:** 2026-11-21

## Context
The original `src/battery_soc.py` mixed configuration loading (with import-time `load_dotenv()` and `sys.exit(1)`), Solarman HTTP logic, and the SinricPro event loop in a single module, with zero automated tests and no linting or type checking. This made both human and AI-agent maintenance error-prone because changes could not be verified offline without live credentials or a physical phone.

## Decision
1. **Refactor into a clean `src/solar_bridge/` package** (`config.py`, `solarman.py`, `bridge.py`, `cli.py`) with zero import-time side effects and dependency injection for HTTP sessions, clocks, and the SinricPro gateway. Keep `src/battery_soc.py` as a thin backwards-compatible shim.
2. **Separate lightweight runtime deps from dev tools:**
   - Runtime (`requirements.txt` and `[project.dependencies]`): pure-Python `requests`, `python-dotenv`, `sinricpro` so Termux installs reliably on ARM Android.
   - Dev (`[project.optional-dependencies] dev`): `pytest`, `pytest-asyncio`, `ruff`, `pyright`.
3. **Mandate offline automated tests & strict Red-Green-Refactor workflow** in `AGENTS.md`, enforced locally via `Makefile` (`make check`) and in GitHub Actions (`.github/workflows/ci.yml`).

## Consequences
- **Pros:** Agents and developers can verify every change offline in seconds with `ruff check .`, `pyright`, `pytest`, and `bash -n` / `shellcheck`; no live credentials or phone hardware required for CI.
- **Cons:** Slightly more files than a single-script project, offset by clear module boundaries and documented invariants in `AGENTS.md` and `docs/system-design.md`.
