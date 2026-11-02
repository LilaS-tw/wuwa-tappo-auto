"""版本／地區綁定的設定，啟動時依已安裝的 Tappo 資料夾自動選 Profile（預設 global）。"""

import os
import sys
from dataclasses import dataclass

APP_VERSION = "1.0.0"


def resource_path(rel: str) -> str:
    """唯讀打包資源；單檔時取自 sys._MEIPASS，否則用專案資料夾。"""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, rel)


def history_path() -> str:
    """「最近獲得」歷史檔（data_dir 下的 history.json）。"""
    return os.path.join(data_dir(), "history.json")


def data_dir() -> str:
    """可寫入資料夾；打包版用 %LOCALAPPDATA%\\WuwaTappoAuto，原始碼版用專案資料夾。"""
    if getattr(sys, "frozen", False):
        d = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "WuwaTappoAuto")
    else:
        d = os.path.dirname(os.path.abspath(__file__))
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


@dataclass(frozen=True)
class Profile:
    name: str                 # 人類可讀名稱
    bundle: str               # %APPDATA% / %LOCALAPPDATA% 下的資料夾名
    environment: str          # 本機檔名與點擊檔內的 environment 欄位
    api_base: str
    # 本機點擊檔 = JSON{"count","cuid","environment"} 以 click_xor_key 重複 XOR
    click_xor_key: bytes = b"kuro-mc-cumulative-click-v1"

    @property
    def appdata_dir(self) -> str:
        return os.path.join(os.environ.get("APPDATA", ""), self.bundle)

    @property
    def webview_dir(self) -> str:
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), self.bundle, "EBWebView")

    @property
    def click_filename(self) -> str:
        return f"cumulative_click_{self.environment}.dat"

    @property
    def click_dat_path(self) -> str:
        return os.path.join(self.appdata_dir, self.click_filename)

    @property
    def ui_locale_path(self) -> str:
        return os.path.join(self.appdata_dir, "ui-locale.txt")

    def is_installed(self) -> bool:
        return os.path.isdir(self.appdata_dir)


# --- 內建設定檔 -----------------------------------
GLOBAL = Profile(
    name="Global",
    bundle="com.kuro.wuwatappo.global",
    environment="global-global-prod",
    api_base="https://api-wutheringwaves-wuwatappo.kurogames-global.com",
)
# 若要支援國服，於此新增 Profile（需取得其 bundle / environment / api_base 實際值）。
PROFILES = (GLOBAL,)


def detect_profile() -> Profile:
    """選第一個「已安裝」的設定檔；都沒有就回預設（全球版）。"""
    for p in PROFILES:
        if p.is_installed():
            return p
    return GLOBAL


# --- 啟動時解析使用中的設定檔，並匯出常用常數供其他模組直接引用 ---------
ACTIVE = detect_profile()

APP_BUNDLE = ACTIVE.bundle
ENVIRONMENT = ACTIVE.environment
API_BASE = ACTIVE.api_base
CLICK_XOR_KEY = ACTIVE.click_xor_key
CLICK_FILENAME = ACTIVE.click_filename

# WebView2 程序（記憶體掃描用）
WEBVIEW_PROCESS = "msedgewebview2.exe"
PROCESS_CMDLINE_MATCH = "wuwatappo"

# Cookie（token 與到期時間）
COOKIE_TOKEN_NAME = "kuro_infoToken"
COOKIE_EXPIRE_NAME = "kuro_lastLoginTime"


def appdata_dir() -> str:
    return ACTIVE.appdata_dir


def webview_dir() -> str:
    return ACTIVE.webview_dir


def click_dat_path() -> str:
    return ACTIVE.click_dat_path


def ui_locale_path() -> str:
    return ACTIVE.ui_locale_path
