import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

PYPI_URL = "https://pypi.org/pypi/{}/json"
PYPI_SIMPLE = "https://pypi.org/simple/"

_pypi_opener = urllib.request.build_opener(urllib.request.HTTPHandler())
_pypi_opener.addheaders = [("User-Agent", "Mozilla/5.0")]


class DescriptionService:
    def __init__(self):
        self._cache = {}
        self._full_cache = {}
        self._lock = threading.Lock()
        self._search_cache = {}
        self._search_lock = threading.Lock()
        self._popular_cache = []
        self._popular_loaded = threading.Event()
        self._request_count = 0
        self._request_lock = threading.Lock()
        self._last_request_time = 0
        self._min_interval = 0.05
        self._start_popular_load()

    def _throttle(self):
        with self._request_lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request_time = time.time()
            self._request_count += 1

    def _start_popular_load(self):
        def load():
            try:
                self._throttle()
                req = urllib.request.Request(PYPI_SIMPLE, headers={"User-Agent": "Mozilla/5.0"})
                with _pypi_opener.open(req, timeout=15) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
                matches = re.findall(r'href="/simple/([^/]+)/"', html)
                seen = set()
                out = []
                for m in matches:
                    low = m.lower()
                    if low in seen:
                        continue
                    seen.add(low)
                    out.append(m)
                    if len(out) >= 500:
                        break
                with self._search_lock:
                    self._popular_cache = out
                    self._popular_loaded.set()
            except Exception:
                self._popular_loaded.set()

        threading.Thread(target=load, daemon=True).start()

    def get(self, name):
        with self._lock:
            return self._cache.get(name, "")

    def fetch(self, name):
        with self._lock:
            if name in self._cache:
                return self._cache[name]
        try:
            self._throttle()
            req = urllib.request.Request(PYPI_URL.format(name), headers={"User-Agent": "Mozilla/5.0"})
            with _pypi_opener.open(req, timeout=10) as resp:
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
            self._throttle()
            req = urllib.request.Request(PYPI_URL.format(name), headers={"User-Agent": "Mozilla/5.0"})
            with _pypi_opener.open(req, timeout=10) as resp:
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
        except Exception as e:
            logger.debug("get_info failed for %s: %s", name, e)
            result = {"summary": "", "description": "", "home_page": "", "license": "", "requires_dist": [], "project_urls": {}}
        with self._lock:
            self._full_cache[name + "__info"] = result
        return result

    def search(self, query):
        query = (query or "").strip()
        if len(query) < 2:
            return []
        qlow = query.lower()
        with self._search_lock:
            cached = self._search_cache.get(qlow)
            if cached is not None:
                return cached
        result = []
        try:
            self._throttle()
            req = urllib.request.Request(f"https://pypi.org/simple/?q={urllib.parse.quote(query)}", headers={"User-Agent": "Mozilla/5.0"})
            with _pypi_opener.open(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            matches = re.findall(r'href="/simple/([^/]+)/"', html)
            seen = set()
            for m in matches:
                low = m.lower()
                if low in seen:
                    continue
                seen.add(low)
                if qlow in low:
                    result.append(m)
                    if len(result) >= 30:
                        break
        except Exception as e:
            logger.debug("search failed for %s: %s", query, e)
        if not result:
            with self._search_lock:
                pop = list(self._popular_cache)
            seen = set()
            for m in pop:
                low = m.lower()
                if low in seen:
                    continue
                seen.add(low)
                if qlow in low:
                    result.append(m)
                    if len(result) >= 30:
                        break
        if result:
            with self._search_lock:
                self._search_cache[qlow] = result
        return result

    def fetch_many(self, names, max_workers=8):
        results = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_name = {executor.submit(self.fetch, name): name for name in names}
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    results[name] = future.result()
                except Exception:
                    results[name] = ""
        return results
