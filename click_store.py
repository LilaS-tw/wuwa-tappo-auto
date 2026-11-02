"""讀取 Tappo 本機累計點擊檔（XOR 編碼的 JSON）；檔案一更新即等於伺服器點擊數。"""

import json
import os
from dataclasses import dataclass
from typing import Optional

import config

XOR_KEY = config.CLICK_XOR_KEY
ENVIRONMENT = config.ENVIRONMENT
DAT_PATH = config.click_dat_path()


@dataclass
class ClickState:
    count: int
    cuid: str
    mtime_ns: int


def decode(raw: bytes) -> dict:
    return json.loads(bytes(b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(raw)))


class ClickFile:
    """可呼叫物件，回傳最新 ClickState；檔案未變不重讀，讀不到回 None。"""

    def __init__(self, path: str = DAT_PATH):
        self.path = path
        self._cached: Optional[ClickState] = None

    def __call__(self) -> Optional[ClickState]:
        try:
            mtime_ns = os.stat(self.path).st_mtime_ns
        except OSError:
            return None
        if self._cached and self._cached.mtime_ns == mtime_ns:
            return self._cached
        try:
            with open(self.path, "rb") as f:
                data = decode(f.read())
            if data.get("environment") != ENVIRONMENT:
                return None
            self._cached = ClickState(int(data["count"]), str(data.get("cuid", "")), mtime_ns)
        except (OSError, ValueError, KeyError, TypeError):
            # Tappo 寫到一半等情況：沿用上一次的值，下一秒再讀
            return self._cached
        return self._cached
