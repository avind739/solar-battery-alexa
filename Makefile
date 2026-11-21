PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PYTEST ?= $(if $(wildcard .venv/bin/pytest),.venv/bin/pytest,pytest)
RUFF ?= $(if $(wildcard .venv/bin/ruff),.venv/bin/ruff,ruff)
PYRIGHT ?= $(if $(wildcard .venv/bin/pyright),.venv/bin/pyright,pyright)

.PHONY: test lint format typecheck shellcheck check

test:
	$(PYTEST)

lint:
	$(RUFF) check .

format:
	$(RUFF) format .

typecheck:
	$(PYRIGHT)

shellcheck:
	bash -n scripts/*.sh
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck scripts/*.sh; else echo "shellcheck not installed; syntax checked with bash -n"; fi

check: lint typecheck test shellcheck
