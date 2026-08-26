"""Self-check for the pyright stdout-parsing logic in _run_pyright_on_file.

Run directly: `python tests/test_pyright_parsing.py`.
"""

from unittest.mock import MagicMock, patch

from quri_sdk_mcp.py_checker.pyright_check import _run_pyright_on_file


def _fake_process(stdout, stderr="", returncode=0):
    process = MagicMock()
    process.stdout = stdout
    process.stderr = stderr
    process.returncode = returncode
    return process


def test_zero_errors_summary_line_marks_success():
    stdout = "No configuration file found.\n0 errors, 0 warnings, 0 informations \n"
    with patch("subprocess.run", return_value=_fake_process(stdout)):
        result = _run_pyright_on_file("/tmp/code.py", "/venv/bin/pyright")
    assert result["success"] is True
    assert result["errors"] == []


def test_error_summary_line_marks_failure_and_extracts_error_message():
    stdout = (
        '/tmp/code.py:3:5 - error: "foo" is not defined (reportUndefinedVariable)\n'
        "1 error, 0 warnings, 0 informations \n"
    )
    with patch("subprocess.run", return_value=_fake_process(stdout)):
        result = _run_pyright_on_file("/tmp/code.py", "/venv/bin/pyright")
    assert result["success"] is False
    assert result["errors"] == ['"foo" is not defined']


def test_alternate_found_errors_summary_pattern():
    stdout = "found 2 errors\n"
    with patch("subprocess.run", return_value=_fake_process(stdout, returncode=1)):
        result = _run_pyright_on_file("/tmp/code.py", "/venv/bin/pyright")
    assert result["success"] is False


def test_no_errors_found_summary_pattern_marks_success():
    stdout = "No errors found\n"
    with patch("subprocess.run", return_value=_fake_process(stdout)):
        result = _run_pyright_on_file("/tmp/code.py", "/venv/bin/pyright")
    assert result["success"] is True


def test_file_path_replaced_with_placeholder_in_output():
    stdout = (
        "/tmp/code.py:1:1 - error: bad (someRule)\n1 error, 0 warnings, 0 informations \n"
    )
    with patch("subprocess.run", return_value=_fake_process(stdout)):
        result = _run_pyright_on_file("/tmp/code.py", "/venv/bin/pyright")
    assert "/tmp/code.py" not in result["output"]
    assert "[checked_code.py]" in result["output"]


def test_missing_pyright_executable_reported_as_failure():
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        result = _run_pyright_on_file("/tmp/code.py", "/venv/bin/pyright")
    assert result["success"] is False
    assert "not found" in result["errors"][0].lower()


if __name__ == "__main__":
    test_zero_errors_summary_line_marks_success()
    test_error_summary_line_marks_failure_and_extracts_error_message()
    test_alternate_found_errors_summary_pattern()
    test_no_errors_found_summary_pattern_marks_success()
    test_file_path_replaced_with_placeholder_in_output()
    test_missing_pyright_executable_reported_as_failure()
    print("ok")
