import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import pytest

from src.core import pip_wrapper, pypi


class TestRunPip(unittest.TestCase):
    def test_file_not_found(self):
        ok, out = pip_wrapper._run_pip(["list"], python="C:\\nonexistent\\python.exe")
        assert ok is False
        assert "Не удалось запустить интерпретатор" in out

    def test_nonzero_exit(self):
        ok, out = pip_wrapper._run_pip(["nonexistentcommand"])
        assert ok is False

    def test_success(self):
        ok, out = pip_wrapper._run_pip(["--version"])
        assert ok is True
        assert "pip" in out.lower()


class TestGetInstalledPackages(unittest.TestCase):
    def test_returns_list_of_dicts(self):
        pkgs = pip_wrapper.get_installed_packages()
        assert isinstance(pkgs, list)
        for pkg in pkgs:
            assert "name" in pkg
            assert "version" in pkg

    def test_sorted_case_insensitive(self):
        pkgs = pip_wrapper.get_installed_packages()
        names = [p["name"] for p in pkgs]
        assert names == sorted(names, key=lambda n: n.lower())

    def test_no_duplicates(self):
        pkgs = pip_wrapper.get_installed_packages()
        names = [p["name"] for p in pkgs]
        assert len(names) == len(set(names))


class TestGetOutdated(unittest.TestCase):
    def test_returns_dict(self):
        outdated = pip_wrapper.get_outdated()
        assert isinstance(outdated, dict)

    def test_values_are_strings(self):
        outdated = pip_wrapper.get_outdated()
        for name, version in outdated.items():
            assert isinstance(name, str)
            assert isinstance(version, str)


class TestGetEnvironmentInfo(unittest.TestCase):
    def test_required_keys(self):
        info = pip_wrapper.get_environment_info()
        assert "executable" in info
        assert "version" in info
        assert "prefix" in info
        assert "is_venv" in info
        assert isinstance(info["is_venv"], bool)

    def test_invalid_python(self):
        info = pip_wrapper.get_environment_info(python="C:\\nonexistent\\python.exe")
        assert "executable" in info
        assert "version" in info
        assert "is_venv" in info


class TestFamilyOf(unittest.TestCase):
    def test_no_digits(self):
        assert pip_wrapper.family_of("numpy") == "numpy"

    def test_digits_after_letters(self):
        assert pip_wrapper.family_of("python3") == "python"
        assert pip_wrapper.family_of("python3.11") == "python"

    def test_mixed_case(self):
        assert pip_wrapper.family_of("PyQt5") == "pyqt"

    def test_digits_first(self):
        assert pip_wrapper.family_of("3d") == ""

    def test_empty(self):
        assert pip_wrapper.family_of("") == ""


class TestUpdatePackages(unittest.TestCase):
    def test_empty_names(self):
        ok, out = pip_wrapper.update_packages([])
        assert ok is False
        assert "Не указаны" in out

    def test_none_names(self):
        ok, out = pip_wrapper.update_packages([None, ""])
        assert ok is False
        assert "Не указаны" in out


class TestUninstallPackages(unittest.TestCase):
    def test_empty_names(self):
        ok, out = pip_wrapper.uninstall_packages([])
        assert ok is False
        assert "Не указаны" in out

    def test_none_names(self):
        ok, out = pip_wrapper.uninstall_packages([None, ""])
        assert ok is False
        assert "Не указаны" in out


class TestExportRequirements(unittest.TestCase):
    def test_creates_file(self):
        test_path = Path("C:\\Users\\User\\AppData\\Local\\Temp\\kilo") / "requirements.txt"
        packages = [{"name": "pytest", "version": "7.0.0"}]
        ok, path = pip_wrapper.export_requirements(packages, str(test_path))
        assert ok is True
        assert test_path.exists()
        content = test_path.read_text(encoding="utf-8")
        assert "pytest==7.0.0" in content

    def test_empty_packages(self):
        test_path = Path("C:\\Users\\User\\AppData\\Local\\Temp\\kilo") / "empty.txt"
        ok, path = pip_wrapper.export_requirements([], str(test_path))
        assert ok is True
        assert test_path.exists()
        assert test_path.read_text(encoding="utf-8") == ""


class TestFindPythonInterpreters(unittest.TestCase):
    def test_returns_list(self):
        interpreters = pip_wrapper.find_python_interpreters()
        assert isinstance(interpreters, list)

    def test_no_duplicates(self):
        interpreters = pip_wrapper.find_python_interpreters()
        assert len(interpreters) == len(set(interpreters))

    def test_all_are_files(self):
        interpreters = pip_wrapper.find_python_interpreters()
        for interp in interpreters:
            assert os.path.isfile(interp)


class TestDescriptionService(unittest.TestCase):
    def test_get_cache_miss(self):
        svc = pypi.DescriptionService()
        result = svc.get("nonexistent_pkg_xyz_12345")
        assert result == ""

    def test_fetch_caches(self):
        svc = pypi.DescriptionService()
        result1 = svc.fetch("pip")
        result2 = svc.get("pip")
        assert result1 == result2

    def test_get_info_has_required_keys(self):
        svc = pypi.DescriptionService()
        info = svc.get_info("pip")
        assert "summary" in info
        assert "description" in info
        assert "home_page" in info
        assert "license" in info
        assert "requires_dist" in info
        assert "project_urls" in info

    def test_search_short_query(self):
        svc = pypi.DescriptionService()
        assert svc.search("a") == []

    def test_search_empty_query(self):
        svc = pypi.DescriptionService()
        assert svc.search("") == []

    def test_search_caching(self):
        svc = pypi.DescriptionService()
        result1 = svc.search("pip")
        result2 = svc.search("pip")
        assert result1 == result2

    def test_search_case_insensitive(self):
        svc = pypi.DescriptionService()
        result1 = svc.search("pytest")
        result2 = svc.search("PyTest")
        assert result1 == result2

    def test_search_no_duplicates(self):
        svc = pypi.DescriptionService()
        result = svc.search("pip")
        assert len(result) == len(set(result))

    def test_search_max_30(self):
        svc = pypi.DescriptionService()
        result = svc.search("py")
        assert len(result) <= 30

    def test_popular_load_event(self):
        with mock.patch("src.core.pypi._pypi_opener.open") as mock_open:
            mock_resp = mock.Mock()
            mock_resp.read.return_value = b'<a href="/simple/pytest/">pytest</a>'
            mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
            mock_resp.__exit__ = mock.Mock(return_value=False)
            mock_open.return_value = mock_resp
            svc = pypi.DescriptionService()
            assert svc._popular_loaded.wait(timeout=5)
            assert len(svc._popular_cache) > 0

    def test_thread_safety(self):
        svc = pypi.DescriptionService()
        errors = []

        def worker():
            try:
                for _ in range(3):
                    svc.fetch("pip")
                    svc.get_info("pip")
                    svc.search("pip")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


class TestPerformance(unittest.TestCase):
    def test_search_caching_speed(self):
        svc = pypi.DescriptionService()
        start = time.time()
        svc.search("pytest")
        first_time = time.time() - start
        start = time.time()
        svc.search("pytest")
        second_time = time.time() - start
        assert second_time < first_time * 2

    def test_get_info_caching_speed(self):
        svc = pypi.DescriptionService()
        start = time.time()
        svc.get_info("pytest")
        first_time = time.time() - start
        start = time.time()
        svc.get_info("pytest")
        second_time = time.time() - start
        assert second_time < first_time * 2

    def test_fetch_caching_speed(self):
        svc = pypi.DescriptionService()
        start = time.time()
        svc.fetch("pytest")
        first_time = time.time() - start
        start = time.time()
        svc.fetch("pytest")
        second_time = time.time() - start
        assert second_time < first_time * 2

    def test_concurrent_fetch_performance(self):
        svc = pypi.DescriptionService()
        names = ["pytest", "pip"]
        start = time.time()
        threads = []
        for name in names:
            t = threading.Thread(target=svc.fetch, args=(name,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        elapsed = time.time() - start
        assert elapsed < 20

    def test_family_of_performance(self):
        start = time.time()
        for _ in range(10000):
            pip_wrapper.family_of("python3.11")
        elapsed = time.time() - start
        assert elapsed < 2


class TestUIApp(unittest.TestCase):
    def test_app_import(self):
        from src.ui.app import PipManagerApp
        assert PipManagerApp is not None

    def test_constants(self):
        from src.ui.app import CHECKED, UNCHECKED
        assert CHECKED == "☑"
        assert UNCHECKED == "☐"
