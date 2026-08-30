from typing import Any

import contextlib
import hashlib
import subprocess
import tempfile
import os
import random
import shutil
import sys
import time
import json
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

from quri_sdk_mcp.env_resolution import resolve_target_python

VENV_PRUNE_TTL_DAYS = 30
VENV_FRESHNESS_TTL_DAYS = 1
VENV_CACHE_PRUNE_PROBABILITY = 1 / 20
VENV_LOCK_TIMEOUT_SECONDS = 600.0


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
        if venv_dir.name.endswith(".lock"):
            continue
        marker = venv_dir / ".ready"
        # Hold the same lock _venv_lock uses before deleting, so a caller that
        # acquires it right after can't have its venv pulled out from under
        # it. The staleness check itself races another prune/rebuild's
        # rmtree of this same dir, so it stays inside the same try/except.
        try:
            if not (marker.exists() and marker.stat().st_mtime < cutoff):
                continue
            with _try_venv_lock(cache_root, venv_dir.name):
                shutil.rmtree(venv_dir, ignore_errors=True)
        except OSError:
            continue  # lock held, or another call already deleted this dir


def _venv_executable(venv_dir: Path, name: str) -> str:
    """Resolves the path to an executable installed inside a venv."""
    bin_dir = "Scripts" if sys.platform == "win32" else "bin"
    suffix = ".exe" if sys.platform == "win32" else ""
    return str(venv_dir / bin_dir / f"{name}{suffix}")


def _lock_file_nonblocking(handle) -> None:
    """Raises OSError if another process already holds the lock."""
    if sys.platform == "win32":
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle) -> None:
    if sys.platform == "win32":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle, fcntl.LOCK_UN)


@contextlib.contextmanager
def _try_venv_lock(cache_root: Path, cache_key: str):
    """Attempts to acquire the venv lock without blocking; raises OSError if
    another process already holds it. A real OS file lock, so a crashed
    holder's lock is released by the kernel rather than guessed via a
    staleness timeout, and there is no window where the lock is absent while
    a holder is still using the venv (unlike a lock-file-exists check).
    """
    lock_path = cache_root / f"{cache_key}.lock"
    with open(lock_path, "w") as handle:
        _lock_file_nonblocking(handle)
        try:
            yield
        finally:
            _unlock_file(handle)


@contextlib.contextmanager
def _venv_lock(cache_root: Path, cache_key: str):
    """Cross-process lock so concurrent calls for the same cache key don't race
    on venv creation. Blocks (polling) until acquired or VENV_LOCK_TIMEOUT_SECONDS
    elapses. Acquisition failure (OSError) is only caught around the attempt
    itself, not the caller's body, so an OSError raised inside the `with`
    block still propagates instead of being mistaken for lock contention.
    """
    lock_path = cache_root / f"{cache_key}.lock"
    deadline = time.monotonic() + VENV_LOCK_TIMEOUT_SECONDS
    with open(lock_path, "w") as handle:
        while True:
            try:
                _lock_file_nonblocking(handle)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Timed out waiting for venv lock: {cache_key}")
                time.sleep(0.2)
        try:
            yield
        finally:
            _unlock_file(handle)


def _is_venv_fresh(marker_path: Path) -> bool:
    """Whether a cached venv was created within VENV_FRESHNESS_TTL_DAYS."""
    try:
        data = json.loads(marker_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if not data or "created_at" not in data:
        return False
    return time.time() - data["created_at"] <= VENV_FRESHNESS_TTL_DAYS * 86400


def _target_python_environment(python: Path) -> tuple[str, list[str]]:
    """Returns the target interpreter's language version and import paths."""
    script = (
        "import json, sys\n"
        "print(json.dumps({"
        "'version': f'{sys.version_info.major}.{sys.version_info.minor}', "
        "'import_paths': [p for p in sys.path if p]}))\n"
    )
    process = subprocess.run(
        [str(python), "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(process.stdout)
    return data["version"], data["import_paths"]


def create_pyrightconfig(
    venv_path: Path,
    project_dir: Path | None = None,
    python_version: str | None = None,
    extra_paths: list[str] | None = None,
) -> dict:
    """
    Create a pyrightconfig.json file for the given virtual environment.

    Args:
        venv_path: Path to the virtual environment directory
        project_dir: Directory containing the code being checked.

    Returns:
        The created pyrightconfig.json's contents.
    """
    config = {
        "pythonVersion": python_version
        or f"{sys.version_info.major}.{sys.version_info.minor}",
        "venvPath": str(venv_path.parent.absolute()),
        "venv": venv_path.name,
        "typeCheckingMode": "basic",
        "useLibraryCodeForTypes": True,
        "reportMissingImports": True,
        "reportMissingTypeStubs": False,
        "executionEnvironments": [{"root": ".", "extraPaths": extra_paths or []}],
    }

    config_path = (project_dir or venv_path) / "pyrightconfig.json"
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    return config


def _run_pyright_on_file(
    code_file_to_check: str,
    pyright_command: list[str],
    project_dir: str,
    target_python: str | None = None,
) -> dict:
    """Runs Pyright (via its `--outputjson` mode) on a specified file.

    `pyright_command` invokes this server's own pinned Pyright (see
    pyproject.toml), not one installed into the disposable venv being
    checked - Pyright resolves that venv's packages via `--pythonpath`/
    `venvPath` config instead, so it never needs to live inside it.

    Success/failure and per-diagnostic messages come straight from Pyright's
    own structured output, not from parsing its human-readable text - that
    output's exact wording isn't a stable contract, its JSON schema is. File
    paths in the reconstructed `output` summary are replaced with a
    placeholder.
    """
    check_result = {"success": False, "output": "", "errors": []}
    # Placeholder to display instead of temporary file paths
    # To use a fixed filename in feedback to AI
    file_placeholder = "[checked_code.py]"

    try:
        command = list(pyright_command) + ["-p", project_dir, "--outputjson"]
        if target_python is not None:
            command.extend(["--pythonpath", target_python])
        command.append(code_file_to_check)
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        try:
            data = json.loads(process.stdout)
        except json.JSONDecodeError:
            raw_output = (process.stdout + process.stderr).replace(
                code_file_to_check, file_placeholder
            )
            check_result["output"] = raw_output.strip()
            check_result["errors"] = [f"Could not parse Pyright output: {raw_output.strip()}"]
            return check_result

        diagnostics = data.get("generalDiagnostics", [])
        summary = data.get("summary", {})
        check_result["success"] = summary.get("errorCount", 0) == 0
        check_result["errors"] = [
            d["message"] for d in diagnostics if d.get("severity") == "error"
        ]
        check_result["output"] = "\n".join(
            [
                f"{file_placeholder}:{d['range']['start']['line'] + 1}"
                f":{d['range']['start']['character'] + 1} - {d['severity']}: {d['message']}"
                + (f" ({d['rule']})" if d.get("rule") else "")
                for d in diagnostics
            ]
            + [
                f"{summary.get('errorCount', 0)} errors, "
                f"{summary.get('warningCount', 0)} warnings, "
                f"{summary.get('informationCount', 0)} informations"
            ]
        )

    except FileNotFoundError:
        check_result["output"] = (
            f"Error: Pyright command {pyright_command!r} not found."
        )
        check_result["errors"].append(
            f"Pyright command {pyright_command!r} not found."
        )
        check_result["success"] = False
    except Exception as e:
        check_result["output"] = (
            f"An unexpected error occurred during Pyright check: {str(e)}"
        )
        check_result["errors"].append(f"An unexpected error: {str(e)}")
        check_result["success"] = False
    return check_result


def _empty_result() -> dict[str, Any]:
    """The all-steps-pending shape returned by `run_code_in_temporary_venv`,
    also used for a timeout result raised before any step could run."""
    return {
        "venv_path": None,
        "target_python": None,
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


def timeout_result(message: str) -> dict[str, Any]:
    """Builds a `run_code_in_temporary_venv`-shaped result for a caller that
    caught the `TimeoutError` `_venv_lock` can raise."""
    result = _empty_result()
    result["log"].append(message)
    return result


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
    results = _empty_result()

    target_python = resolve_target_python()
    results["target_python"] = str(target_python)
    try:
        python_version_tag, target_import_paths = _target_python_environment(
            target_python
        )
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError) as e:
        results["log"].append(
            f"Failed to inspect target Python environment {target_python}: {e}"
        )
        return results

    cache_root = _venv_cache_root()
    _prune_stale_venvs(cache_root)

    target_tag = f"{python_version_tag}@{target_python.absolute()}"
    cache_key = _venv_cache_key(dependencies, target_tag)
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
            try:
                subprocess.run(
                    [str(target_python), "-m", "venv", str(venv_dir)],
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

            # 2. Install dependencies. Pyright itself runs from this server's
            # own pinned install (see pyproject.toml), not from this
            # disposable venv - see _run_pyright_on_file.
            packages_to_install = list(dependencies)

            if not packages_to_install:
                results["dependencies_installed"] = True
                results["log"].append("No extra dependencies to install.")
                marker_path.write_text(json.dumps({"created_at": time.time()}))
            else:
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
                    results["dependencies_installed"] = True
                    results["log"].append(
                        f"Packages installed successfully:\n{install_proc.stdout}"
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
        pyright_command = [sys.executable, "-m", "pyright"]

        # 3. Write AI code and its Pyright project config to a unique directory
        # outside the shared cached venv.
        with tempfile.TemporaryDirectory(prefix="ai_code_check_") as check_dir_name:
            check_dir = Path(check_dir_name)
            ai_code_path = check_dir / "checked_code.py"
            ai_code_path.write_text(ai_code_string, encoding="utf-8")
            pyright_config = create_pyrightconfig(
                venv_dir,
                project_dir=check_dir,
                python_version=python_version_tag,
                extra_paths=target_import_paths,
            )
            results["log"].append(
                f"Pyright configured as {json.dumps(pyright_config, indent=2)}"
            )
            results["log"].append(f"AI code written to: {ai_code_path}")

            # 4. Perform Pyright static check
            pyright_result = _run_pyright_on_file(
                str(ai_code_path),
                pyright_command,
                str(check_dir),
                target_python=str(target_python),
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
                                env={
                                    **os.environ,
                                    "PYTHONPATH": os.pathsep.join(
                                        target_import_paths
                                        + ([os.environ["PYTHONPATH"]] if "PYTHONPATH" in os.environ else [])
                                    ),
                                },
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
            results["log"].append(f"Cleaned up AI code directory: {check_dir}")

    return results
