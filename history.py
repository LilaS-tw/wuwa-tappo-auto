"""「最近獲得」歷史的讀寫，順序舊→新，上限 MAX_ITEMS。"""

import json
import logging
import os

log = logging.getLogger(__name__)

MAX_ITEMS = 60


def make_entry(res, ts) -> dict:
    """由開箱結果建立一筆歷史（ts 為 epoch 秒）。"""
    return {
        "asset_id": res.asset_id,
        "asset_type": res.asset_type or "",
        "asset_name": res.asset_name or "",
        "rarity_type": res.rarity_type or "",
        "ts": int(ts),
    }


def _normalize(obj):
    """正規化單筆，不合格回 None。"""
    if not isinstance(obj, dict):
        return None
    try:
        ts = int(obj.get("ts"))
    except (TypeError, ValueError):
        return None
    return {
        "asset_id": obj.get("asset_id"),
        "asset_type": str(obj.get("asset_type") or ""),
        "asset_name": str(obj.get("asset_name") or ""),
        "rarity_type": str(obj.get("rarity_type") or ""),
        "ts": ts,
    }


def load(path) -> list:
    """讀取歷史。檔案不存在或壞掉回空清單；超過上限只保留最新的 MAX_ITEMS 筆。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        log.warning("history load failed: %s", type(e).__name__)
        return []
    if not isinstance(data, list):
        return []
    items = [e for e in (_normalize(x) for x in data) if e is not None]
    return items[-MAX_ITEMS:]


def save(path, items) -> bool:
    """原子寫入（先寫 .tmp 再 os.replace）。失敗只記錄、回 False，不丟例外。"""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(list(items[-MAX_ITEMS:]), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError as e:
        log.warning("history save failed: %s", type(e).__name__)
        return False


def append(items: list, entry: dict) -> list:
    """附加一筆並裁到上限（原地修改並回傳同一個 list）。"""
    items.append(entry)
    del items[:-MAX_ITEMS]
    return items
