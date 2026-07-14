import json
import platform
import subprocess
import sys


def get_installed_packages():
    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    data = json.loads(result.stdout)
    packages = [{"name": pkg["name"], "version": pkg.get("version", "")} for pkg in data]
    packages.sort(key=lambda p: p["name"].lower())
    return packages


def get_environment_info():
    is_venv = sys.prefix != sys.base_prefix
    return {
        "executable": sys.executable,
        "version": platform.python_version(),
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "is_venv": is_venv,
    }


def family_of(name):
    # Группируем по базовому имени: обрезаем всё, начиная с первой цифры.
    # "pyqt4"/"pyqt5" -> "pyqt"; "python"/"python3"/"python3.11" -> "python".
    # Имена без цифр (python-dateutil) остаются своим собственным семейством.
    idx = next((i for i, c in enumerate(name) if c.isdigit()), None)
    return name[:idx].lower() if idx is not None else name.lower()


def uninstall_packages(names):
    cmd = [sys.executable, "-m", "pip", "uninstall", "-y"] + list(names)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stdout + result.stderr
