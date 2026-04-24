"""End-to-end test suite — Part 8 Stage 3.

Runs the full pipeline against a real Ollama instance with the three
SystemConfig-default models. Opt-in only via `slow` pytest marker; skipped
by `make test` / `make test-fast`. See `harness.py` for the shared preflight
and KPI classification helpers, and the `test_*_app.py` files for the three
reference projects (Todo / Blog / Guestbook).
"""
