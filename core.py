"""Tappo 後端 API 封裝；只用 user/me、renew-token、chests/open，絕不呼叫登入／登出端點。"""

import email.utils
import time
from dataclasses import dataclass
from typing import Callable, Optional

import requests

import config

API_BASE = config.API_BASE
TIMEOUT_S = 15

BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
    ),
}

AUTH_CODES = {10002, 10003}   # 登入失效 / 已過期
NOT_ENOUGH_CLICKS_CODE = 70005


# ---------------------------------------------------------------------------
# 錯誤分類
# ---------------------------------------------------------------------------
class ApiError(Exception):
    """伺服器回傳非 0 的 code，或非 2xx 的 HTTP 狀態（非登入失效）。"""

    def __init__(self, code=None, message="", http_status=None):
        super().__init__(f"code={code} {message}".strip())
        self.code = code
        self.message = message
        self.http_status = http_status


class AuthError(ApiError):
    """HTTP 401/403 或 code 10002/10003：token 失效。"""


class NotEnoughClicks(ApiError):
    """code 70005：點擊數不足以開箱。"""


class NetworkError(Exception):
    """連線層失敗（逾時、DNS、連線被拒…）。"""


# ---------------------------------------------------------------------------
# 回傳資料
# ---------------------------------------------------------------------------
@dataclass
class UserMe:
    nickname: Optional[str]
    total_click_count: Optional[int]
    total_click_consume: Optional[int]
    left_ms: Optional[int]
    right_ms: Optional[int]
    server_ms: Optional[int]
    cuid: Optional[str] = None


@dataclass
class OpenResult:
    asset_name: Optional[str]
    asset_type: Optional[str]
    rarity_type: Optional[str]
    click_consume: Optional[int]
    left_next_ms: Optional[int]
    right_next_ms: Optional[int]
    server_ms: Optional[int]
    asset_id: Optional[int] = None   # 對應資產目錄的鍵


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def now_ms() -> int:
    return int(time.time() * 1000)


def parse_date_header_ms(value: Optional[str]) -> Optional[int]:
    """HTTP Date 標頭 → epoch 毫秒。"""
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    return int(dt.timestamp() * 1000)


# ---------------------------------------------------------------------------
# API 客戶端
# ---------------------------------------------------------------------------
class TappoApi:
    """每個回應都會更新 offset_ms（伺服器時間 - 本機時間）。"""

    def __init__(self, session=None, clock: Callable[[], int] = now_ms, base: str = API_BASE):
        self._session = session or requests.Session()
        self._clock = clock
        self._base = base
        self.offset_ms = 0

    def _request(self, method: str, path: str, token: Optional[str] = None, body=None):
        headers = dict(BASE_HEADERS)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        t0 = self._clock()
        try:
            r = self._session.request(
                method, self._base + path, headers=headers, json=body, timeout=TIMEOUT_S
            )
        except requests.RequestException as e:
            raise NetworkError(type(e).__name__) from e
        t1 = self._clock()

        server_ms = parse_date_header_ms(r.headers.get("Date"))
        if server_ms is not None:
            self.offset_ms = server_ms - (t0 + t1) // 2

        status = r.status_code
        if status in (401, 403):
            raise AuthError(None, f"HTTP {status}", status)
        try:
            j = r.json()
        except ValueError:
            raise ApiError(None, f"HTTP {status} 非 JSON 回應", status)
        if not isinstance(j, dict):
            raise ApiError(None, f"HTTP {status} 非預期格式", status)

        code = j.get("code")
        message = j.get("message") or ""
        if code in AUTH_CODES:
            raise AuthError(code, message, status)
        if code == NOT_ENOUGH_CLICKS_CODE:
            raise NotEnoughClicks(code, message, status)
        if status >= 400 or code not in (0, None):
            raise ApiError(code, message, status)
        return j.get("data"), server_ms

    # -- public -------------------------------------------------------------
    def get_user_me(self, token: str) -> UserMe:
        data, server_ms = self._request("GET", "/api/frontend/user/me", token)
        d = data or {}
        return UserMe(
            nickname=d.get("nickname"),
            total_click_count=d.get("total_click_count"),
            total_click_consume=d.get("total_click_consume"),
            left_ms=d.get("left_treasure_chest"),
            right_ms=d.get("right_treasure_chest"),
            server_ms=server_ms,
            cuid=str(d["cuid"]) if d.get("cuid") is not None else None,
        )

    def open_chest(self, token: str, place: str, click_num: int) -> OpenResult:
        data, server_ms = self._request(
            "POST",
            "/api/frontend/chests/open",
            token,
            {"place": place, "click_num": click_num},
        )
        d = data or {}
        return OpenResult(
            asset_name=d.get("asset_name"),
            asset_type=d.get("asset_type"),
            rarity_type=d.get("rarity_type"),
            click_consume=d.get("click_consume"),
            left_next_ms=d.get("left_next_time"),
            right_next_ms=d.get("right_next_time"),
            server_ms=server_ms,
            asset_id=d.get("asset_id"),
        )

    def renew_token(self, token: str) -> bool:
        data, _ = self._request("GET", "/api/frontend/user/renew-token", token)
        return data is True

    def get_assets_host(self) -> Optional[str]:
        """取得資產主機（圖片 CDN base）。"""
        data, _ = self._request("GET", "/api/common/activity-config")
        host = (data or {}).get("assets_host")
        return host.rstrip("/") if isinstance(host, str) and host else None

    def get_appearance_catalog(self, assets_host: str) -> Optional[dict]:
        """取資產目錄（asset_id -> {url,...}，依型別分組）。"""
        if not assets_host:
            return None
        idx = self._session.get(f"{assets_host}/app/json-host/appearance_asset_host.json", timeout=TIMEOUT_S)
        url = (idx.json() or {}).get("url")
        if not url:
            return None
        cat = self._session.get(url, timeout=TIMEOUT_S)
        data = cat.json()
        return data if isinstance(data, dict) else None
