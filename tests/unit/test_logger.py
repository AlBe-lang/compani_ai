from __future__ import annotations

import json

import pytest

from observability.ids import generate_run_id
from observability.logger import configure_logging, get_logger


def _capture_payload(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    payload = json.loads(capsys.readouterr().out.strip())
    assert isinstance(payload, dict)

    normalized: dict[str, object] = {}
    for key, value in payload.items():
        assert isinstance(key, str)
        normalized[key] = value
    return normalized


def test_logger_info_outputs_json(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(force=True)
    run_id = generate_run_id()
    logger = get_logger(component="unit-test", run_id=run_id)

    logger.info("logger_info_test", detail="ok")
    payload = _capture_payload(capsys)

    assert payload["event"] == "logger_info_test"
    assert payload["component"] == "unit-test"
    assert payload["run_id"] == run_id
    assert payload["detail"] == "ok"


def test_logger_warning_outputs_level(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(force=True)
    logger = get_logger(component="unit-test")

    logger.warning("logger_warning_test")
    payload = _capture_payload(capsys)

    assert payload["event"] == "logger_warning_test"
    assert payload["level"] == "warning"


def test_logger_error_outputs_level(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(force=True)
    logger = get_logger(component="unit-test")

    logger.error("logger_error_test", error_code="E-PARSE-JSON")
    payload = _capture_payload(capsys)

    assert payload["event"] == "logger_error_test"
    assert payload["level"] == "error"
    assert payload["error_code"] == "E-PARSE-JSON"


def test_logger_debug_outputs_level(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(force=True)
    logger = get_logger(component="unit-test")

    logger.debug("logger_debug_test")
    payload = _capture_payload(capsys)

    assert payload["event"] == "logger_debug_test"
    assert payload["level"] == "debug"
