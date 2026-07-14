import json
import os
import platform
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import winreg
from pathlib import Path


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
    ok, output = _run_pip(["list", "--format=json"], python)
    if not ok:
        raise RuntimeError(output or "pip list завершился с ошибкой")
    try:
        data = json.loads(output)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Некорректный ответ pip: {e}") from e
    packages = [{"name": pkg["name"], "version": pkg.get("version", "")} for pkg in data]
    packages.sort(key=lambda p: p["name"].lower())
    return packages


def get_outdated(python=None):
    ok, output = _run_pip(["list", "--outdated", "--format=json"], python)
    if not ok:
        return {}
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return {}
    return {pkg["name"]: pkg.get("latest_version", "") for pkg in data}


def search_pypi(query):
    query = (query or "").strip()
    if len(query) < 2:
        return []
    try:
        url = f"https://pypi.org/simple/?q={urllib.parse.quote(query)}"
        with urllib.request.urlopen(url, timeout=8) as resp:
            html = resp.read().decode("utf-8")
        matches = re.findall(r'href="/simple/([^/]+)/"', html)
        seen = set()
        out = []
        for m in matches:
            low = m.lower()
            if low in seen:
                continue
            seen.add(low)
            if query.lower() in low:
                out.append(m)
                if len(out) >= 30:
                    break
        return out
    except Exception:
        return []


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


def install_packages(specs, python=None):
    specs = [s for s in specs if s]
    if not specs:
        return False, "Не указаны пакеты для установки"
    return _run_pip(["install", *specs], python)


def update_packages(names, python=None):
    names = [n for n in names if n]
    if not names:
        return False, "Не указаны пакеты для обновления"
    return _run_pip(["install", "--upgrade", *names], python)


def uninstall_packages(names, python=None):
    names = [n for n in names if n]
    if not names:
        return False, "Не указаны пакеты для удаления"
    return _run_pip(["uninstall", "-y", *names], python)


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
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Python\PythonCore")
        for i in range(winreg.QueryInfoKey(key)[0]):
            try:
                name = winreg.EnumKey(key, i)
                sub = winreg.OpenKey(key, f"{name}\\InstallPath")
                try:
                    candidate = os.path.join(winreg.QueryValueEx(sub, "")[0], "python.exe")
                    add(candidate)
                except FileNotFoundError:
                    pass
                finally:
                    winreg.CloseKey(sub)
            except OSError:
                break
        winreg.CloseKey(key)
    except OSError:
        pass
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Python\PythonCore")
        for i in range(winreg.QueryInfoKey(key)[0]):
            try:
                name = winreg.EnumKey(key, i)
                sub = winreg.OpenKey(key, f"{name}\\InstallPath")
                try:
                    candidate = os.path.join(winreg.QueryValueEx(sub, "")[0], "python.exe")
                    add(candidate)
                except FileNotFoundError:
                    pass
                finally:
                    winreg.CloseKey(sub)
            except OSError:
                break
        winreg.CloseKey(key)
    except OSError:
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

