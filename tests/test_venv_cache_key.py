"""Self-check for the check_code persistent venv cache key.

Run directly: `python tests/test_venv_cache_key.py`.
"""

from quri_sdk_mcp.py_checker.pyright_check import _venv_cache_key


def test_dependency_order_does_not_change_key():
    assert _venv_cache_key(["b", "a"], "3.13") == _venv_cache_key(["a", "b"], "3.13")


def test_different_dependencies_change_key():
    assert _venv_cache_key(["a"], "3.13") != _venv_cache_key(["a", "b"], "3.13")


def test_different_python_version_changes_key():
    assert _venv_cache_key(["a"], "3.13") != _venv_cache_key(["a"], "3.12")


if __name__ == "__main__":
    test_dependency_order_does_not_change_key()
    test_different_dependencies_change_key()
    test_different_python_version_changes_key()
    print("ok")
