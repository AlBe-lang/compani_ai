PYTHON ?= python

.PHONY: setup format lint test test-fast test-e2e e2e e2e-ask e2e-single e2e-preflight bench bench-mock bench-real pre-commit-install

setup:
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt

# Part 8 Stage 3-4 — R-06A: 로컬 git 훅 활성화. setup 후 1회 실행 권고.
# CI 는 .github/workflows/ci.yml 의 pre-commit job 에서 동일 hooks 강제.
pre-commit-install:
	$(PYTHON) -m pre_commit install

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

# Part 8 Stage 3 — E2E reference projects (Todo / Blog / Guestbook).
#
#   e2e            Non-interactive. Requires CONFIRM_E2E=1. Safe for CI and
#                  scripted invocation. Prints preflight then runs all slow
#                  tests. Refuses to run without the env flag.
#   e2e-ask        Interactive. Prints preflight and asks y/N before kicking
#                  off the full suite. Intended for local manual runs.
#   e2e-single     Run one project only. `make e2e-single PROJECT=todo`.
#                  Also requires CONFIRM_E2E=1.
#   e2e-preflight  Print preflight diagnostic only (no tests run).
#
# All targets use the `slow` marker and require Ollama + the three SystemConfig
# default models (qwen3:8b / gemma4:e4b / llama3.2:3b).
e2e-preflight:
	PYTHONPATH=src $(PYTHON) -c "import asyncio; from tests.e2e.harness import preflight, format_preflight; \
	report=asyncio.run(preflight()); print(format_preflight(report)); \
	exit(0 if report.ready else 1)"

e2e: e2e-preflight
	@if [ -z "$$CONFIRM_E2E" ]; then \
	  echo ""; \
	  echo "E2E 실행은 Ollama + ~30분의 로컬 리소스를 사용합니다."; \
	  echo "실행하려면 CONFIRM_E2E=1 환경변수를 세팅하세요:"; \
	  echo "  CONFIRM_E2E=1 make e2e"; \
	  echo "대화형 확인을 원하시면: make e2e-ask"; \
	  exit 1; \
	fi
	$(PYTHON) -m pytest tests/e2e -m slow -v

e2e-ask: e2e-preflight
	@printf "\nE2E 실행은 ~30분+ 소요됩니다. 계속할까요? [y/N] "; \
	read ans; \
	case "$$ans" in [yY]|[yY][eE][sS]) \
	  $(PYTHON) -m pytest tests/e2e -m slow -v ;; \
	*) echo "취소됨."; exit 0 ;; \
	esac

e2e-single: e2e-preflight
	@if [ -z "$$CONFIRM_E2E" ]; then \
	  echo "CONFIRM_E2E=1 환경변수를 세팅하세요. 예:"; \
	  echo "  CONFIRM_E2E=1 make e2e-single PROJECT=todo"; \
	  exit 1; \
	fi
	@if [ -z "$(PROJECT)" ]; then \
	  echo "PROJECT 변수를 지정하세요. 예: make e2e-single PROJECT=todo"; \
	  exit 1; \
	fi
	$(PYTHON) -m pytest tests/e2e/test_$(PROJECT)_app.py -m slow -v

# Part 8 Stage 1 benchmark targets. Mock and real are kept separate so their
# numbers never get compared — see 개발 일지 Part 8 (1).md §3 for role split.
bench-mock:
	$(PYTHON) -m pytest tests/benchmarks -q -m benchmark

bench-real:
	$(PYTHON) scripts/benchmark_real.py

bench: bench-mock bench-real

# Part 8 Stage 2 — CEO dashboard targets. See 개발 일지 Part 8 (2).md.
# dashboard        Python-only backend server (no pipeline run).
# flutter-pub      Resolve Flutter dependencies (first-time setup).
# flutter-build    Build static web assets → ui/ceo_dashboard/build/web/.
# flutter-run      Hot-reload Flutter dev server (for UI iteration).
# flutter-test     Run Flutter widget tests.
dashboard:
	$(PYTHON) main.py --dashboard

flutter-pub:
	cd ui/ceo_dashboard && flutter pub get

flutter-build:
	cd ui/ceo_dashboard && flutter build web

flutter-run:
	cd ui/ceo_dashboard && flutter run -d chrome

flutter-test:
	cd ui/ceo_dashboard && flutter test
