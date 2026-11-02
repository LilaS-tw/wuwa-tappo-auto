import json
import os

import config
import i18n
import names
import rewards
from scheduler import DISPLAY_ORDER, place_name

SETTINGS_PATH = os.path.join(config.data_dir(), "settings.json")
APPEARANCE_MODES = ("light", "dark", "system")


def load_settings() -> dict:
    defaults = {"auto": True, "appearance": "system", "locale": "auto", "tray": False}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return defaults
    if not isinstance(d, dict):
        return defaults
    loc = d.get("locale", "auto")
    return {
        "auto": bool(d.get("auto", True)),
        "appearance": d.get("appearance") if d.get("appearance") in APPEARANCE_MODES else "system",
        "locale": loc if (loc == "auto" or loc in i18n.LOCALES) else "auto",
        "tray": bool(d.get("tray", False)),
    }


def save_settings(s: dict) -> None:
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


class Api:
    def __init__(self, scheduler, settings, tray_available=False, on_set_tray=None):
        self.s = scheduler
        self.settings = settings
        self.tray_available = tray_available
        self._on_set_tray = on_set_tray
        self.on_minimize = None   # 由 app.py 在建立視窗後接上
        self.on_close = None
        self.on_start_drag = None

    # ---- 讀取整體狀態 ----
    def get_state(self):
        snap = self.s.snapshot()
        loc = i18n.get_locale()
        d = names.load_dict(names.dict_lang(loc))

        def tr(k):
            return i18n.CATALOG.get(loc, {}).get(k) or i18n.CATALOG["en"].get(k, k)

        chests = [{"place": p, "label": place_name(p), "dueMs": snap["due"].get(p),
                   "paused": bool(snap["paused"].get(p))} for p in DISPLAY_ORDER]

        hist = []
        for e in snap.get("history", []):
            atype, aid, aname = e.get("asset_type"), e.get("asset_id"), e.get("asset_name")
            cp = rewards.cached_path(atype, aid)
            hist.append({
                "assetId": aid, "assetType": atype, "assetName": aname,
                "rarityType": e.get("rarity_type"), "ts": e.get("ts"),
                "name": names.display_name(d, atype, aname),
                "img": (f"img/{os.path.basename(cp)}" if cp else None),
            })
        hist.reverse()  # 新 -> 舊

        filters = [
            {"key": "all", "label": tr("hist_all")},
            {"key": "character_skin", "label": tr("hist_character")},
            {"key": "accessory", "label": tr("hist_accessory")},
            {"key": "emote", "label": tr("hist_emote")},
        ]
        lang_options = [{"code": "auto", "label": tr("lang_auto")}] + \
                       [{"code": c, "label": lbl} for c, lbl in i18n.LOCALE_OPTIONS]

        return {
            "status": snap["status"], "nickname": snap["nickname"],
            "auto": snap["auto"], "authStopped": snap["auth_stopped"],
            "totalClickCount": snap["total_click_count"],
            "totalClickConsume": snap["total_click_consume"],
            "offsetMs": snap.get("offset_ms", 0), "clockMs": snap.get("clock_ms"),
            "chests": chests, "history": hist,
            "settings": dict(self.settings),
            "i18n": i18n.CATALOG.get(loc, i18n.CATALOG["en"]),
            "locale": loc, "langOptions": lang_options, "filters": filters,
            "trayAvailable": bool(self.tray_available),
            "version": config.APP_VERSION,
        }

    # ---- 指令 ----
    def set_auto(self, on):
        on = bool(on)
        self.settings["auto"] = on
        save_settings(self.settings)
        self.s.auto_enabled = on
        self.s.post("auto", on)       # 背景執行完整處理（重置暫停、同步）
        self.s._emit()                # 立即推送最新狀態

    def redetect(self):
        self.s.post("redetect")

    def sync_now(self):
        self.s.post("sync")

    def open_chest(self, place):
        if place in ("left", "right"):
            self.s.post("open", place)

    def set_appearance(self, mode):
        if mode in APPEARANCE_MODES:
            self.settings["appearance"] = mode
            save_settings(self.settings)
            self.s._emit()

    def set_locale(self, code):
        if code == "auto" or code in i18n.LOCALES:
            self.settings["locale"] = code
            save_settings(self.settings)
            i18n.set_locale(code)
            self.s.post("ensure_dict")
            self.s._emit()

    def open_log(self):
        try:
            os.startfile(config.data_dir())  # noqa: S606 (Windows 開啟資料夾)
        except Exception:
            pass

    # ---- 自訂標題列：視窗控制 ----
    def minimize_window(self):
        if self.on_minimize:
            self.on_minimize()

    def close_window(self):
        if self.on_close:
            self.on_close()

    def start_drag(self):
        if self.on_start_drag:
            self.on_start_drag()

    def set_tray(self, on):
        self.settings["tray"] = bool(on)
        save_settings(self.settings)
        if self._on_set_tray:
            self._on_set_tray(bool(on))
        self.s._emit()
