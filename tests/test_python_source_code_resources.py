"""Self-check that a target-interpreter resolution failure degrades
python_source_code_resources's module-level doc-ref lookup to "main" instead
of crashing at import time.

Run directly: `python tests/test_python_source_code_resources.py`.
"""

import importlib
import subprocess
from unittest.mock import patch

import quri_sdk_mcp.python_source_code_resources as psr


def test_doc_ref_falls_back_to_main_on_resolution_failure():
    with patch(
        "quri_sdk_mcp.env_resolution.get_versions",
        side_effect=subprocess.CalledProcessError(1, "python"),
    ):
        importlib.reload(psr)
        assert psr._doc_ref == "main"
    importlib.reload(psr)  # restore normal (unpatched) module state


if __name__ == "__main__":
    test_doc_ref_falls_back_to_main_on_resolution_failure()
    print("ok")
