PYTHON ?= python

.PHONY: setup format lint test test-fast test-e2e bench bench-mock bench-real

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

# Default test: unit + integration, excludes slow (Ollama required) and
# benchmark markers. Part 8 Stage 1 added `benchmark` exclusion so developers
# running `make test` don't accidentally trigger performance suites.
test:
	$(PYTHON) -m pytest tests -q -m "not slow and not benchmark"

test-fast:
	$(PYTHON) -m pytest tests -m "not slow and not benchmark" -q

test-e2e:
	$(PYTHON) -m pytest tests/e2e -m slow -q

# Part 8 Stage 1 benchmark targets. Mock and real are kept separate so their
# numbers never get compared — see 개발 일지 Part 8 (1).md §3 for role split.
bench-mock:
	$(PYTHON) -m pytest tests/benchmarks -q -m benchmark

bench-real:
	$(PYTHON) scripts/benchmark_real.py

bench: bench-mock bench-real
