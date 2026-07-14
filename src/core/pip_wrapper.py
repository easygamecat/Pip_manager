import json
import logging
import os
import platform
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_pip_version_cache = None
_pip_version_ts = 0
_PIP_VERSION_TTL = 60

_interpreters_cache = []
_interpreters_ts = 0
_INTERPRETERS_TTL = 300


def _run_pip(args, python=None):
    python = python or sys.executable
    try:
        result = subprocess.run(
            [python, "-m", "pip", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as e:
        return False, f"Не удалось запустить интерпретатор: {e}"
    except subprocess.TimeoutExpired:
        return False, "pip завершился по таймауту"
    return result.returncode == 0, result.stdout + result.stderr


_installed_cache = []
_installed_ts = 0
_INSTALLED_TTL = 300


def get_installed_packages(python=None):
    logger.debug("get_installed_packages: python=%s", python)
    global _installed_cache, _installed_ts
    now = time.time()
    if _installed_cache and now - _installed_ts < _INSTALLED_TTL:
        return list(_installed_cache)

    try:
        from importlib.metadata import distributions
    except ImportError:
        pass
    else:
        try:
            packages = []
            for dist in distributions():
                name = dist.metadata["Name"]
                version = dist.metadata["Version"]
                if name:
                    packages.append({"name": name, "version": version or ""})
            packages.sort(key=lambda p: p["name"].lower())
            _installed_cache = packages
            _installed_ts = now
            logger.info("Found %d packages via importlib.metadata", len(packages))
            return packages
        except Exception as e:
            logger.debug("importlib.metadata fallback failed: %s", e)

    ok, output = _run_pip(["list", "--format=json"], python)
    if not ok:
        logger.error("pip list failed: %s", output)
        raise RuntimeError(output or "pip list завершился с ошибкой")
    try:
        data = json.loads(output)
    except json.JSONDecodeError as e:
        logger.error("pip list json decode failed: %s", e)
        raise RuntimeError(f"Некорректный ответ pip: {e}") from e
    packages = [{"name": pkg["name"], "version": pkg.get("version", "")} for pkg in data]
    packages.sort(key=lambda p: p["name"].lower())
    _installed_cache = packages
    _installed_ts = now
    logger.info("Found %d packages", len(packages))
    return packages


_outdated_cache = {}
_outdated_ts = 0
_OUTDATED_TTL = 60


def get_outdated(python=None):
    logger.debug("get_outdated: python=%s", python)
    global _outdated_cache, _outdated_ts
    now = time.time()
    if _outdated_cache and now - _outdated_ts < _OUTDATED_TTL:
        return dict(_outdated_cache)

    ok, output = _run_pip(["list", "--outdated", "--format=json"], python)
    if not ok:
        logger.warning("pip list --outdated failed: %s", output)
        return {}
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return {}
    outdated = {pkg["name"]: pkg.get("latest_version", "") for pkg in data}
    _outdated_cache = outdated
    _outdated_ts = now
    logger.info("Found %d outdated packages", len(outdated))
    return outdated


def get_environment_info(python=None):
    python = python or sys.executable
    env = {
        "executable": python,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
    }
    global _pip_version_cache, _pip_version_ts
    now = time.time()
    if _pip_version_cache is None or now - _pip_version_ts > _PIP_VERSION_TTL:
        try:
            result = subprocess.run(
                [python, "-m", "pip", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                first = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
                if first.lower().startswith("python"):
                    _pip_version_cache = first.split(" ", 1)[1].strip()
                else:
                    _pip_version_cache = platform.python_version()
            else:
                _pip_version_cache = platform.python_version()
        except Exception:
            _pip_version_cache = platform.python_version()
        _pip_version_ts = now
    env["version"] = _pip_version_cache
    is_venv = False
    try:
        info = subprocess.run(
            [python, "-c", "import sys; print(sys.prefix); print(sys.base_prefix)"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = info.stdout.strip().splitlines()
        if len(lines) == 2:
            is_venv = lines[0] != lines[1]
    except Exception:
        pass
    env["is_venv"] = is_venv
    return env


def family_of(name):
    idx = next((i for i, c in enumerate(name) if c.isdigit()), None)
    return name[:idx].lower() if idx is not None else name.lower()


def update_packages(names, python=None):
    names = [n for n in names if n]
    if not names:
        return False, "Не указаны пакеты для обновления"
    logger.info("Upgrading: %s via %s", names, python)
    ok, out = _run_pip(["install", "--upgrade", *names], python)
    if not ok:
        logger.error("Upgrade failed: %s", out)
    return ok, out


def uninstall_packages(names, python=None):
    names = [n for n in names if n]
    if not names:
        return False, "Не указаны пакеты для удаления"
    logger.info("Uninstalling: %s via %s", names, python)
    ok, out = _run_pip(["uninstall", "-y", *names], python)
    if not ok:
        logger.error("Uninstall failed: %s", out)
    return ok, out


def export_requirements(packages, path):
    with open(path, "w", encoding="utf-8") as f:
        for pkg in packages:
            f.write(f"{pkg['name']}=={pkg['version']}\n")
    return True, path


def find_python_interpreters():
    global _interpreters_cache, _interpreters_ts
    now = time.time()
    if _interpreters_cache and now - _interpreters_ts < _INTERPRETERS_TTL:
        return list(_interpreters_cache)

    found = []
    seen = set()

    def add(python):
        python = str(python)
        if python and python not in seen and os.path.isfile(python):
            seen.add(python)
            found.append(python)

    add(sys.executable)
    try:
        add(os.path.join(sys.base_prefix, "python.exe"))
    except Exception:
        pass
    try:
        for root in [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python",
            Path(os.environ.get("ProgramFiles", "")) / "Python",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Python",
        ]:
            if root.exists():
                for child in root.iterdir():
                    candidate = child / "python.exe"
                    if candidate.exists():
                        add(candidate)
    except Exception:
        pass
    env_path = os.environ.get("PATH", "")
    for part in env_path.split(os.pathsep):
        if not part:
            continue
        try:
            for name in os.listdir(part):
                if name.lower().startswith("python") and name.lower().endswith(".exe"):
                    add(os.path.join(part, name))
        except OSError:
            continue

    _interpreters_cache = found
    _interpreters_ts = now
    return list(found)
