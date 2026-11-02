"""獎勵圖示：依資產目錄 + asset_id 取真圖並快取。"""

import os
import re
import config

CACHE_DIR = os.path.join(config.data_dir(), "cache")

_UUID_URL = re.compile(r"^[A-Za-z0-9_]+/[A-Za-z0-9_.-]+\.(?:png|webp|jpg|jpeg)(?:\?.*)?$", re.I)


def catalog_rel_url(catalog, asset_type, asset_id):
    """從資產目錄查相對 url；查不到回 None。"""
    if not catalog or asset_id is None:
        return None
    section = catalog.get((asset_type or "").strip().lower())
    if not isinstance(section, dict):
        return None
    entry = section.get(str(asset_id))
    if not isinstance(entry, dict):
        return None
    url = entry.get("url")
    if isinstance(url, str) and _UUID_URL.match(url.strip()):
        return url.strip()
    return None


def _cache_name(asset_type, asset_id):
    t = re.sub(r"[^a-z_]", "", (asset_type or "x").lower()) or "x"
    return f"{t}_{int(asset_id)}.png"


def cached_path(asset_type, asset_id):
    """只查快取，已下載回路徑否則 None（不連網）。"""
    try:
        name = _cache_name(asset_type, asset_id)
    except (TypeError, ValueError):
        return None
    path = os.path.join(CACHE_DIR, name)
    return path if os.path.isfile(path) and os.path.getsize(path) > 0 else None


def ensure_reward_image(assets_host, catalog, asset_type, asset_id, session=None, timeout=10):
    """取獎勵圖本機路徑（必要時下載，須在背景執行緒）；失敗回 None。"""
    rel = catalog_rel_url(catalog, asset_type, asset_id)
    if not rel or not assets_host:
        return None
    try:
        name = _cache_name(asset_type, asset_id)
    except (TypeError, ValueError):
        return None
    path = os.path.join(CACHE_DIR, name)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path
    url = f"{assets_host.rstrip('/')}/{rel.lstrip('/')}"
    try:
        import requests
        getter = session.get if session is not None else requests.get
        r = getter(url, timeout=timeout)
        if r.status_code != 200 or "image" not in r.headers.get("Content-Type", ""):
            return None
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(r.content)
        os.replace(tmp, path)
        return path
    except Exception:
        return None
