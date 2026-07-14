import json
import re
import threading
import urllib.parse
import urllib.request

PYPI_URL = "https://pypi.org/pypi/{}/json"


class DescriptionService:
    def __init__(self):
        self._cache = {}
        self._full_cache = {}
        self._lock = threading.Lock()
        self._search_cache = {}
        self._search_lock = threading.Lock()

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
        return self.get_info(name).get("description", "")

    def get_info(self, name):
        with self._lock:
            cached = self._full_cache.get(name + "__info")
            if cached is not None:
                return cached
        try:
            with urllib.request.urlopen(PYPI_URL.format(name), timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            info = data.get("info", {}) or {}
            result = {
                "summary": info.get("summary", "") or "",
                "description": info.get("description", "") or "",
                "home_page": info.get("home_page", "") or "",
                "license": info.get("license", "") or "",
                "requires_dist": info.get("requires_dist") or [],
                "project_urls": info.get("project_urls") or {},
            }
        except Exception:
            result = {"summary": "", "description": "", "home_page": "", "license": "", "requires_dist": [], "project_urls": {}}
        with self._lock:
            self._full_cache[name + "__info"] = result
        return result

    def search(self, query):
        with self._search_lock:
            cached = self._search_cache.get(query)
            if cached is not None:
                return cached
        result = []
        try:
            url = f"https://pypi.org/simple/?q={urllib.parse.quote(query)}"
            with urllib.request.urlopen(url, timeout=8) as resp:
                html = resp.read().decode("utf-8")
            matches = re.findall(r'href="/simple/([^/]+)/"', html)
            seen = set()
            for m in matches:
                low = m.lower()
                if low in seen:
                    continue
                seen.add(low)
                if query.lower() in low:
                    result.append(m)
                    if len(result) >= 30:
                        break
        except Exception:
            pass
        with self._search_lock:
            self._search_cache[query] = result
        return result
