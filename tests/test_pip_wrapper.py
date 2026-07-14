import pytest

from src.core import pip_wrapper


@pytest.mark.parametrize("name,expected", [
    ("pyqt4", "pyqt"),
    ("pyqt5", "pyqt"),
    ("PyQt5-sip", "pyqt"),
    ("python", "python"),
    ("python3", "python"),
    ("python3.11", "python"),
    ("python-dateutil", "python-dateutil"),
    ("numpy", "numpy"),
    ("Django", "django"),
])
def test_family_of(name, expected):
    assert pip_wrapper.family_of(name) == expected


def test_family_of_groups_versioned_names_together():
    families = {pip_wrapper.family_of(n) for n in ["python", "python3", "python3.11"]}
    assert families == {"python"}


def test_get_environment_info_keys():
    info = pip_wrapper.get_environment_info()
    assert {"executable", "version", "prefix", "is_venv"} <= set(info.keys())
    assert isinstance(info["is_venv"], bool)
