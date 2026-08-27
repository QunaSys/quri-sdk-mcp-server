from typing import Any

import contextlib
import hashlib
import subprocess
import tempfile
import os
import random
import shutil
import sys
import re
import time
import json
from pathlib import Path

VENV_PRUNE_TTL_DAYS = 30
VENV_FRESHNESS_TTL_DAYS = 1
VENV_CACHE_PRUNE_PROBABILITY = 1 / 20
VENV_LOCK_TIMEOUT_SECONDS = 600.0
VENV_LOCK_STALE_SECONDS = 900.0


def _venv_cache_root() -> Path:
    """Returns the persistent venv cache directory, creating it if needed."""
    cache_home = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    root = Path(cache_home) / "quri-sdk-mcp" / "venvs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _venv_cache_key(dependencies: list[str], python_version_tag: str) -> str:
    """Computes a stable cache key for a (dependencies, python version) pair."""
    payload = "\n".join(sorted(dependencies)) + python_version_tag
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _prune_stale_venvs(cache_root: Path) -> None:
    """Opportunistically deletes cached venvs untouched for VENV_PRUNE_TTL_DAYS."""
    # ponytail: naive time-based prune, switch to LRU-by-size if disk pressure
    # becomes real
    if random.random() >= VENV_CACHE_PRUNE_PROBABILITY:
        return
    cutoff = time.time() - VENV_PRUNE_TTL_DAYS * 86400
    for venv_dir in cache_root.iterdir():
        marker = venv_dir / ".ready"
        if marker.exists() and marker.stat().st_mtime < cutoff:
            shutil.rmtree(venv_dir, ignore_errors=True)


def _venv_executable(venv_dir: Path, name: str) -> str:
    """Resolves the path to an executable installed inside a venv."""
    bin_dir = "Scripts" if sys.platform == "win32" else "bin"
    suffix = ".exe" if sys.platform == "win32" else ""
    return str(venv_dir / bin_dir / f"{name}{suffix}")


@contextlib.contextmanager
def _venv_lock(cache_root: Path, cache_key: str):
    """Cross-process advisory lock so concurrent calls for the same cache key don't
    race on venv creation. Path.mkdir() without exist_ok is atomic on POSIX and NTFS.
    """
    lock_dir = cache_root / f"{cache_key}.lock"
    deadline = time.monotonic() + VENV_LOCK_TIMEOUT_SECONDS
    while True:
        try:
            lock_dir.mkdir()
            break
        except FileExistsError:
            try:
                age = time.time() - lock_dir.stat().st_mtime
            except FileNotFoundError:
                continue  # holder released it between our mkdir and stat
            if age > VENV_LOCK_STALE_SECONDS:
                # ponytail: age-based stale-lock steal, no pid-liveness check;
                # revisit if a crashed holder is ever actually observed
                shutil.rmtree(lock_dir, ignore_errors=True)
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"Timed out waiting for venv lock: {cache_key}")
            time.sleep(0.2)
    try:
        yield
    finally:
        shutil.rmtree(lock_dir, ignore_errors=True)


def _venv_marker_data(marker_path: Path) -> dict | None:
    """Reads the venv marker's JSON payload, or None if missing/unreadable."""
    try:
        return json.loads(marker_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _is_venv_fresh(marker_path: Path) -> bool:
    """Whether a cached venv was created within VENV_FRESHNESS_TTL_DAYS."""
    data = _venv_marker_data(marker_path)
    if not data or "created_at" not in data:
        return False
    return time.time() - data["created_at"] <= VENV_FRESHNESS_TTL_DAYS * 86400


def create_pyrightconfig(venv_path: Path) -> Path:
    """
    Create a pyrightconfig.json file for the given virtual environment.
    
    Args:
        venv_path: Path to the virtual environment directory
        output_dir: Directory where the config file should be created
        
    Returns:
        Path to the created pyrightconfig.json file
    """
    # Get the venv name and parent directory
    venv_name = venv_path.name
    venv_parent = venv_path.parent
    
    # Determine the Python executable path based on OS
    python_path = _venv_executable(venv_path, "python")
    
    # Create the configuration
    config = {
        "venv": venv_name,
        "venvPath": str(venv_parent),
        "pythonVersion": f"{sys.version_info.major}.{sys.version_info.minor}",
        "pythonPath": python_path,
        "typeCheckingMode": "basic",
        "useLibraryCodeForTypes": True,
        "reportMissingImports": True,
        "reportMissingTypeStubs": False,
        "executionEnvironments": [
            {
                "root": "."
            }
        ]
    }
    
    # Write the config file
    config_path = venv_path / "pyrightconfig.json"
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    return config_path

# This is the core Pyright checking logic adapted from our previous conversation.
# It will be called by the main function to check code using a specific Pyright executable.
def _run_pyright_on_file(
    code_file_to_check: str, pyright_executable_in_venv: str, project_dir: str
) -> dict:
    """Runs Pyright on a specified file using a specific Pyright executable.

    Parses the output to extract errors and determine success. File paths in the output
    are replaced with a placeholder.
    """
    check_result = {"success": False, "output": "", "errors": []}
    # Placeholder to display instead of temporary file paths
    # To use a fixed filename in feedback to AI
    file_placeholder = "[checked_code.py]"

    try:
        process = subprocess.run(
            [pyright_executable_in_venv, "-p", project_dir, code_file_to_check],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        raw_output = process.stdout + process.stderr

        # Success/failure determination (based on Pyright's summary line)
        num_errors = -1
        summary_patterns = [
            re.compile(
                r"(\d+)\s*error[s]?,\s*(\d+)\s*warning[s]?,\s*(\d+)\s*information[s]?",
                re.IGNORECASE,
            ),
            re.compile(r"found\s*(\d+)\s*error[s]?", re.IGNORECASE),
            re.compile(r"no\s*error[s]?\s*found", re.IGNORECASE),
        ]

        for pattern in summary_patterns:
            match = pattern.search(raw_output)
            if match:
                if pattern.pattern == summary_patterns[0].pattern:
                    num_errors = int(match.group(1))
                    break
                elif pattern.pattern == summary_patterns[1].pattern:
                    num_errors = int(match.group(1))
                    break
                elif pattern.pattern == summary_patterns[2].pattern:
                    num_errors = 0
                    break

        if num_errors == 0:
            check_result["success"] = True
        elif num_errors > 0:
            check_result["success"] = False
        else:
            if process.returncode == 0 and not "error" in raw_output.lower():
                check_result["success"] = True
            elif process.returncode != 0:
                check_result["success"] = False
            else:
                check_result["success"] = False

        # Clean Pyright output by replacing the temporary file path
        cleaned_output_lines = []
        for line in raw_output.splitlines():
            cleaned_line = line.replace(code_file_to_check, file_placeholder)
            cleaned_output_lines.append(cleaned_line)
        check_result["output"] = "\n".join(cleaned_output_lines).strip()

        # Extract pure error messages
        parsed_errors = []
        for line in raw_output.splitlines():  # Parse from raw_output
            marker = " - error: "
            marker_index = line.lower().find(marker)
            if marker_index != -1:
                message_body = line[marker_index + len(marker) :].strip()
                message_body = re.sub(
                    r"\s*\([a-zA-Z0-9_-]+\)$",
                    "",
                    message_body,  # Remove trailing (ruleName)
                ).strip()
                parsed_errors.append(message_body)
            elif (
                ": error: " in line.lower() and code_file_to_check in line
            ):  # Handle other formats if they contain the specific file
                try:
                    _prefix_part, msg_body = line.split(" error: ", 1)
                    msg_body = re.sub(
                        r"\s*\([a-zA-Z0-9_-]+\)$", "", msg_body.strip()
                    ).strip()
                    parsed_errors.append(msg_body)
                except ValueError:
                    pass  # Could not split, ignore this line for error parsing
        check_result["errors"] = parsed_errors

    except FileNotFoundError:
        check_result["output"] = (
            f"Error: Pyright executable '{pyright_executable_in_venv}' not found."
        )
        check_result["errors"].append(
            f"Pyright executable '{pyright_executable_in_venv}' not found."
        )
        check_result["success"] = False
    except Exception as e:
        check_result["output"] = (
            f"An unexpected error occurred during Pyright check: {str(e)}"
        )
        check_result["errors"].append(f"An unexpected error: {str(e)}")
        check_result["success"] = False
    return check_result


def run_code_in_temporary_venv(
    ai_code_string: str,
    dependencies: list[str],
    execute_code_after_check: bool = False,
) -> dict[str, Any]:
    """Creates a temporary virtual environment, installs dependencies and Pyright,
    statically checks the AI-generated code with Pyright, and optionally executes the
    code.

    Args:
        ai_code_string: The Python code string to check and execute.
        dependencies: A list of Python package dependencies (e.g., ["requests", "numpy>=1.20"]).
        execute_code_after_check: If True, executes the code after a successful Pyright check.

    Returns:
        dict: A dictionary containing results from each step.
    """
    results = {
        "venv_path": None,
        "venv_created": False,
        "dependencies_installed": False,
        "pyright_check_result": None,
        "code_execution_result": {
            "executed": False,
            "success": None,
            "stdout": None,
            "stderr": None,
            "return_code": None,
        },
        "log": [],  # Overall log of operations
    }

    cache_root = _venv_cache_root()
    _prune_stale_venvs(cache_root)

    python_version_tag = f"{sys.version_info.major}.{sys.version_info.minor}"
    cache_key = _venv_cache_key(dependencies, python_version_tag)
    venv_dir = cache_root / cache_key
    marker_path = venv_dir / ".ready"
    results["venv_path"] = str(venv_dir)

    with _venv_lock(cache_root, cache_key):
        if venv_dir.is_dir() and marker_path.exists() and _is_venv_fresh(marker_path):
            results["venv_created"] = True
            results["dependencies_installed"] = True
            results["log"].append(f"Reusing cached venv: {venv_dir}")
            marker_path.touch()  # refresh last-used time for the prune TTL
        else:
            if venv_dir.exists():
                shutil.rmtree(venv_dir, ignore_errors=True)

            # 1. Create the virtual environment
            # ponytail: always the server's own interpreter, not resolve_target_python().
            # Dependencies are freshly pip-installed either way, so only the venv's
            # Python *language* version would change; not worth an extra subprocess
            # call in the cache-key computation for that.
            try:
                subprocess.run(
                    [sys.executable, "-m", "venv", str(venv_dir)],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                results["venv_created"] = True
                results["log"].append("Virtual environment created successfully.")
            except subprocess.CalledProcessError as e:
                results["log"].append(f"Venv creation failed: {e.stderr}")
                shutil.rmtree(venv_dir, ignore_errors=True)
                return results  # Critical failure, stop here

            pip_exe = _venv_executable(venv_dir, "pip")

            # 2. Install dependencies and Pyright
            # Pyright CLI is available via pip as 'pyright'
            packages_to_install = dependencies + ["pyright"]
            if not packages_to_install:  # Ensure there's at least 'pyright'
                packages_to_install = ["pyright"]
            elif "pyright" not in packages_to_install:
                packages_to_install.append("pyright")

            try:
                install_command = [pip_exe, "install"] + packages_to_install
                results["log"].append(f"Installing packages: {' '.join(install_command)}")
                install_proc = subprocess.run(
                    install_command,
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                pyright_config_path = create_pyrightconfig(venv_dir)
                results["dependencies_installed"] = True
                results["log"].append(
                    f"Packages installed successfully:\n{install_proc.stdout}"
                )
                with open(pyright_config_path, "r") as f:
                    results["log"].append(
                        f"Pyright configured as {f.read()}"
                    )
                marker_path.write_text(json.dumps({"created_at": time.time()}))
            except subprocess.CalledProcessError as e:
                results["log"].append(
                    f"Package installation failed for {pip_exe} install {' '.join(packages_to_install)}:\n{e.stderr}\nStdout was:\n{e.stdout}"
                )
                shutil.rmtree(venv_dir, ignore_errors=True)
                return results  # Critical failure

        # Venv usage (pyright + optional execution) stays inside the lock so a
        # concurrent call can't rebuild/rmtree this venv while it's in use.
        pyright_exe = _venv_executable(venv_dir, "pyright")

        # 3. Write AI code to a file in the system temp dir (not the shared, cached
        # venv dir, so concurrent calls reusing the same venv don't collide).
        fd, ai_code_path = tempfile.mkstemp(prefix="ai_code_", suffix=".py")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(ai_code_string)
            results["log"].append(f"AI code written to: {ai_code_path}")

            # 4. Perform Pyright static check
            pyright_result = _run_pyright_on_file(
                ai_code_path, pyright_exe, str(venv_dir)
            )
            results["pyright_check_result"] = pyright_result
            results["log"].append(
                f"Pyright check completed. Success: {pyright_result['success']}"
            )
            if not pyright_result["success"]:
                results["log"].append(
                    f"Pyright found errors:\n{pyright_result['output']}"
                )
                # Optionally, you might not want to proceed if Pyright fails.
                # For now, we'll record it and proceed based on execute_code_after_check.

            # 5. Optionally execute the code if Pyright check was successful (or if forced)
            if execute_code_after_check:
                if not pyright_result["success"]:
                    results["log"].append(
                        "Skipping code execution due to Pyright errors."
                    )
                    results["code_execution_result"]["executed"] = (
                        True  # Attempted, but skipped
                    )
                    results["code_execution_result"]["success"] = False
                    results["code_execution_result"]["stderr"] = (
                        "Skipped due to Pyright errors."
                    )
                else:
                    results["code_execution_result"]["executed"] = True
                    try:
                        # ponytail: copy before executing untrusted code so the persisted
                        # cache tree is never mutated by whatever the code does.
                        with tempfile.TemporaryDirectory(
                            prefix="ai_code_venv_"
                        ) as tmp_dir:
                            exec_venv_dir = Path(tmp_dir) / "venv"
                            shutil.copytree(venv_dir, exec_venv_dir)
                            exec_python_exe = _venv_executable(
                                exec_venv_dir, "python"
                            )
                            results["log"].append(
                                f"Executing AI code with: {exec_python_exe} {ai_code_path}"
                            )
                            exec_proc = subprocess.run(
                                [exec_python_exe, ai_code_path],
                                capture_output=True,
                                text=True,
                                encoding="utf-8",
                                timeout=30,  # Added timeout
                            )
                        results["code_execution_result"]["success"] = (
                            exec_proc.returncode == 0
                        )
                        results["code_execution_result"]["stdout"] = exec_proc.stdout
                        results["code_execution_result"]["stderr"] = exec_proc.stderr
                        results["code_execution_result"]["return_code"] = (
                            exec_proc.returncode
                        )
                        results["log"].append(
                            f"Code execution finished. Return code: {exec_proc.returncode}"
                        )
                    except subprocess.TimeoutExpired:
                        results["log"].append("Code execution timed out.")
                        results["code_execution_result"]["success"] = False
                        results["code_execution_result"]["stderr"] = (
                            "Execution timed out after 30 seconds."
                        )
                    except Exception as e:
                        results["log"].append(
                            f"Code execution threw an exception: {str(e)}"
                        )
                        results["code_execution_result"]["success"] = False
                        results["code_execution_result"]["stderr"] = str(e)
        finally:
            # Clean up the temporary AI code file
            if os.path.exists(ai_code_path):
                os.remove(ai_code_path)
                results["log"].append(f"Cleaned up AI code file: {ai_code_path}")

    return results
