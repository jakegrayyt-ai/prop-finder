"""Tiny JSON file cache that survives between GitHub Actions runs (via actions/cache)."""
import json
import os
import re
import time

CACHE_DIR = os.environ.get("PROP_CACHE_DIR", "cache")


def _path(key):
    safe = re.sub(r"[^A-Za-z0-9_./-]", "_", key)
    return os.path.join(CACHE_DIR, safe + ".json")


def get(key, ttl=None):
    """Return cached value if present and younger than ttl seconds (ttl=None: never expires)."""
    p = _path(key)
    try:
        with open(p) as f:
            blob = json.load(f)
    except (OSError, ValueError):
        return None
    if ttl is not None and time.time() - blob.get("_ts", 0) > ttl:
        return None
    return blob.get("data")


def put(key, data):
    p = _path(key)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"_ts": time.time(), "data": data}, f, separators=(",", ":"))
    os.replace(tmp, p)
    return data


def cached(key, ttl, fetch):
    v = get(key, ttl)
    if v is not None:
        return v
    return put(key, fetch())
