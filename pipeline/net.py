"""Small HTTP helpers: one requests session per thread, retries with backoff."""
import random
import threading
import time

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

_local = threading.local()


class FetchError(Exception):
    pass


def session():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})
        _local.s = s
    return s


def get_json(url, params=None, tries=4, timeout=25):
    """GET a URL and return parsed JSON. Retries on 429/5xx and network errors."""
    last = None
    for attempt in range(tries):
        try:
            r = session().get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                raise FetchError(f"HTTP 404 for {r.url}")
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                wait = r.headers.get("Retry-After")
                try:
                    wait = float(wait)
                except (TypeError, ValueError):
                    wait = (2 ** attempt) + random.random()
                time.sleep(min(30.0, wait))
                continue
            raise FetchError(f"HTTP {r.status_code} for {r.url}: {r.text[:200]}")
        except (requests.ConnectionError, requests.Timeout, ValueError) as e:
            last = repr(e)[:200]
            time.sleep(min(30.0, (2 ** attempt) + random.random()))
    raise FetchError(f"failed after {tries} tries: {url} ({last})")
