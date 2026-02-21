PYTHON ?= python

.PHONY: setup format lint test test-fast test-e2e

setup:
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt

format:
	$(PYTHON) -m black src tests
	$(PYTHON) -m isort src tests

lint:
	$(PYTHON) -m black --check src tests
	$(PYTHON) -m isort --check-only src tests
	$(PYTHON) -m flake8 src tests
	$(PYTHON) -m mypy src tests

test:
	$(PYTHON) -m pytest tests -q

test-fast:
	$(PYTHON) -m pytest tests -m "not slow" -q

test-e2e:
	$(PYTHON) -m pytest tests/e2e -m slow -q

