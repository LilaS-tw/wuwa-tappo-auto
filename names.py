import json
import logging
import os
import time
import config

log = logging.getLogger(__name__)

DICT_HOST_PATH = "/app/json-host/dict_host.json"
TIMEOUT_S = 10
# 快取多久內不重新下載（秒）；字典只在新角色/配件上架時才變動
DICT_MAX_AGE_S = 24 * 3600

# i18n 語言代碼 -> 字典檔語言代碼（pt 對應 pt_br）；未知語言回退英文
LANG_MAP = {
    "en": "en", "tw": "tw", "jp": "jp", "kr": "kr", "fr": "fr",
    "de": "de", "es": "es", "pt": "pt_br", "th": "th",
}
DEFAULT_DICT_LANG = "en"

EMOTE_SEP = "・"   # 「・」，角色名與表情動作之間的分隔


def dict_lang(locale) -> str:
    """i18n 語言代碼 -> 字典 lang（未知回 en）。"""
    return LANG_MAP.get(str(locale or "").strip().lower(), DEFAULT_DICT_LANG)


def cache_path(lang: str) -> str:
    return os.path.join(config.data_dir(), f"dict_{lang}.json")


def _is_dict_payload(data) -> bool:
    return isinstance(data, dict) and any(isinstance(data.get(k), dict) for k in ("character", "accessory", "emote"))


def load_dict(lang: str):
    """只讀磁碟快取。檔案不存在或壞掉回 None（不連網）。"""
    try:
        with open(cache_path(lang), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if _is_dict_payload(data) else None


def _fresh(path: str, max_age_s: float) -> bool:
    try:
        return time.time() - os.path.getmtime(path) < max_age_s
    except OSError:
        return False


def ensure_dict(assets_host, lang: str, session=None, max_age_s: float = DICT_MAX_AGE_S, timeout=TIMEOUT_S):
    path = cache_path(lang)
    if _fresh(path, max_age_s):
        cached = load_dict(lang)
        if cached is not None:
            return cached
    try:
        if not assets_host:
            return load_dict(lang)
        getter = session.get if session is not None else _requests_get()
        base = str(assets_host).rstrip("/")
        idx = getter(base + DICT_HOST_PATH, timeout=timeout)
        if idx.status_code != 200:
            return load_dict(lang)
        urls = (idx.json() or {}).get("url") or {}
        url = urls.get(lang) if isinstance(urls, dict) else None
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            return load_dict(lang)
        r = getter(url, timeout=timeout)
        if r.status_code != 200:
            return load_dict(lang)
        data = r.json()
        if not _is_dict_payload(data):
            return load_dict(lang)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return data
    except Exception as e:   # 字典取不到就沿用舊快取或回退名稱
        log.info("dict fetch failed (%s): %s", lang, type(e).__name__)
        return load_dict(lang)


def _requests_get():
    import requests
    return requests.get


def _section(d, key):
    if not isinstance(d, dict):
        return {}
    sec = d.get(key)
    return sec if isinstance(sec, dict) else {}


def _strip_png(asset_name) -> str:
    s = str(asset_name or "").strip()
    return s[:-4] if s.lower().endswith(".png") else s


def display_name(d, asset_type, asset_name) -> str:
    """依字典取資產顯示名；查不到就回退去掉 .png 的 asset_name。"""
    base = _strip_png(asset_name)
    tokens = base.split("_")
    kind = str(asset_type or "").strip().lower()
    try:
        if kind == "character_skin" and len(tokens) >= 2:
            name = _section(d, "character").get(tokens[1])
        elif kind == "emote" and len(tokens) >= 3:
            role = _section(d, "character").get(tokens[1])
            action = _section(d, "emote").get(tokens[-1])
            if role and action:
                name = f"{role}{EMOTE_SEP}{action}"
            else:
                name = role or action
        elif kind == "emote" and len(tokens) == 2:
            name = _section(d, "emote").get(tokens[1])   # 基礎表情 emote_{action}
        elif kind == "accessory" and len(tokens) >= 2:
            name = _section(d, "accessory").get(tokens[1])
        else:
            name = None
    except (TypeError, AttributeError):
        name = None
    return str(name).strip() if name else base
