import json
import threading
import urllib.request

PYPI_URL = "https://pypi.org/pypi/{}/json"


class DescriptionService:
    def __init__(self):
        self._cache = {}
        self._full_cache = {}
        self._lock = threading.Lock()

    def get(self, name):
        with self._lock:
            return self._cache.get(name, "")

    def fetch(self, name):
        with self._lock:
            if name in self._cache:
                return self._cache[name]
        try:
            with urllib.request.urlopen(PYPI_URL.format(name), timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            summary = (data.get("info", {}) or {}).get("summary", "") or ""
        except Exception:
            summary = ""
        with self._lock:
            self._cache[name] = summary
        return summary

    def get_full(self, name):
        with self._lock:
            return self._full_cache.get(name, "")

    def fetch_full(self, name):
        with self._lock:
            if name in self._full_cache:
                return self._full_cache[name]
        try:
            with urllib.request.urlopen(PYPI_URL.format(name), timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            description = (data.get("info", {}) or {}).get("description", "") or ""
        except Exception:
            description = ""
        with self._lock:
            self._full_cache[name] = description
        return description
