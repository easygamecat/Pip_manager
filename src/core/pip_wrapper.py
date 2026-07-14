import json
import logging
import os
import platform
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import winreg
from pathlib import Path

logger = logging.getLogger(__name__)


def _run_pip(args, python=None):
    python = python or sys.executable
    try:
        result = subprocess.run(
            [python, "-m", "pip", *args],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as e:
        return False, f"Не удалось запустить интерпретатор: {e}"
    return result.returncode == 0, result.stdout + result.stderr


def get_installed_packages(python=None):
    logger.debug("get_installed_packages: python=%s", python)
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
    logger.info("Found %d packages", len(packages))
    return packages


def get_outdated(python=None):
    logger.debug("get_outdated: python=%s", python)
    ok, output = _run_pip(["list", "--outdated", "--format=json"], python)
    if not ok:
        logger.warning("pip list --outdated failed: %s", output)
        return {}
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return {}
    outdated = {pkg["name"]: pkg.get("latest_version", "") for pkg in data}
    logger.info("Found %d outdated packages", len(outdated))
    return outdated


def get_environment_info(python=None):
    python = python or sys.executable
    env = {
        "executable": python,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
    }
    ok, output = _run_pip(["--version"], python)
    if ok:
        first = output.strip().splitlines()[0] if output.strip() else ""
        if first.lower().startswith("python"):
            env["version"] = first.split(" ", 1)[1].strip()
        else:
            env["version"] = platform.python_version()
    else:
        env["version"] = platform.python_version()
    is_venv = False
    try:
        info = subprocess.run(
            [python, "-c", "import sys; print(sys.prefix); print(sys.base_prefix)"],
            capture_output=True, text=True,
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
    return found


