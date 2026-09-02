"""Self-check for the pyright --outputjson parsing logic in _run_pyright_on_file.

Run directly: `python tests/test_pyright_parsing.py`.
"""

import json
from unittest.mock import MagicMock, patch

from quri_sdk_mcp.py_checker.pyright_check import _run_pyright_on_file


def _fake_process(data, stderr="", returncode=0):
    process = MagicMock()
    process.stdout = json.dumps(data)
    process.stderr = stderr
    process.returncode = returncode
    return process


def _diagnostic(message, rule=None, severity="error", line=2, character=4):
    diagnostic = {
        "file": "/tmp/code.py",
        "severity": severity,
        "message": message,
        "range": {"start": {"line": line, "character": character}, "end": {}},
    }
    if rule:
        diagnostic["rule"] = rule
    return diagnostic


def test_zero_errors_marks_success():
    data = {
        "generalDiagnostics": [],
        "summary": {"errorCount": 0, "warningCount": 0, "informationCount": 0},
    }
    with patch("subprocess.run", return_value=_fake_process(data)):
        result = _run_pyright_on_file("/tmp/code.py", "/venv/bin/pyright", "/venv")
    assert result["success"] is True
    assert result["errors"] == []


def test_error_diagnostic_marks_failure_and_extracts_message():
    data = {
        "generalDiagnostics": [
            _diagnostic('"foo" is not defined', rule="reportUndefinedVariable")
        ],
        "summary": {"errorCount": 1, "warningCount": 0, "informationCount": 0},
    }
    with patch("subprocess.run", return_value=_fake_process(data)):
        result = _run_pyright_on_file("/tmp/code.py", "/venv/bin/pyright", "/venv")
    assert result["success"] is False
    assert result["errors"] == ['"foo" is not defined']


def test_warnings_alone_still_mark_success():
    # errorCount is what determines success/failure, not diagnostic presence.
    data = {
        "generalDiagnostics": [_diagnostic("unused import", severity="warning")],
        "summary": {"errorCount": 0, "warningCount": 1, "informationCount": 0},
    }
    with patch("subprocess.run", return_value=_fake_process(data)):
        result = _run_pyright_on_file("/tmp/code.py", "/venv/bin/pyright", "/venv")
    assert result["success"] is True
    assert result["errors"] == []


def test_file_path_replaced_with_placeholder_in_output():
    data = {
        "generalDiagnostics": [_diagnostic("bad", rule="someRule")],
        "summary": {"errorCount": 1, "warningCount": 0, "informationCount": 0},
    }
    with patch("subprocess.run", return_value=_fake_process(data)):
        result = _run_pyright_on_file("/tmp/code.py", "/venv/bin/pyright", "/venv")
    assert "/tmp/code.py" not in result["output"]
    assert "[checked_code.py]" in result["output"]
    assert "(someRule)" in result["output"]


def test_missing_pyright_executable_reported_as_failure():
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        result = _run_pyright_on_file("/tmp/code.py", "/venv/bin/pyright", "/venv")
    assert result["success"] is False
    assert "not found" in result["errors"][0].lower()


def test_unparseable_output_reported_as_failure():
    process = MagicMock(stdout="not json", stderr="", returncode=1)
    with patch("subprocess.run", return_value=process):
        result = _run_pyright_on_file("/tmp/code.py", "/venv/bin/pyright", "/venv")
    assert result["success"] is False
    assert result["errors"]


def test_target_python_is_passed_to_pyright():
    data = {
        "generalDiagnostics": [],
        "summary": {"errorCount": 0, "warningCount": 0, "informationCount": 0},
    }
    with patch("subprocess.run", return_value=_fake_process(data)) as run:
        result = _run_pyright_on_file(
            "/tmp/code.py",
            "/venv/bin/pyright",
            "/project",
            target_python="/target/bin/python",
        )

    assert result["success"] is True
    assert run.call_args.args[0] == [
        "/venv/bin/pyright",
        "-p",
        "/project",
        "--outputjson",
        "--pythonpath",
        "/target/bin/python",
        "/tmp/code.py",
    ]


if __name__ == "__main__":
    test_zero_errors_marks_success()
    test_error_diagnostic_marks_failure_and_extracts_message()
    test_warnings_alone_still_mark_success()
    test_file_path_replaced_with_placeholder_in_output()
    test_missing_pyright_executable_reported_as_failure()
    test_unparseable_output_reported_as_failure()
    test_target_python_is_passed_to_pyright()
    print("ok")
