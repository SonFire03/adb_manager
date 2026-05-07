PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
PYTEST ?= .venv/bin/pytest
RUFF ?= .venv/bin/ruff
BLACK ?= .venv/bin/black

.PHONY: deps lint fmt-check test coverage core-coverage check release-check

deps:
	$(PIP) install -r requirements.txt
	$(PIP) install pytest pytest-cov ruff black

lint:
	$(RUFF) check .

fmt-check:
	$(BLACK) --check .

test:
	$(PYTEST) -q

coverage:
	$(PYTEST) -q --cov --cov-report=term-missing --cov-fail-under=80

core-coverage:
	$(PYTEST) -q --cov --cov-report=term-missing --cov-fail-under=80
	coverage report --include="core/*" --fail-under=85
	coverage report --include="modules/data_transfer.py" --fail-under=90

check: lint fmt-check test

release-check:
	./scripts/release_check.sh
