"""取得 Tappo session token（不呼叫登入 API）：快取 → 掃 Tappo 程序記憶體 → 讀 WebView2 Cookie 檔。"""

import base64
import hashlib
import ctypes
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import time
from collections import namedtuple
from ctypes import wintypes
from pathlib import Path
from typing import Optional

import psutil
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import config

log = logging.getLogger(__name__)

APP_DIR = config.data_dir()
CACHE_PATH = os.path.join(APP_DIR, "token_cache.json")

TokenInfo = namedtuple("TokenInfo", "token expire_ms source")

TOKEN_RE = re.compile(re.escape(config.COOKIE_TOKEN_NAME).encode() + rb"=([0-9a-f]{64})")
EXPIRE_RE = re.compile(re.escape(config.COOKIE_EXPIRE_NAME).encode() + rb"=(\d{10,13})")
COOKIE_NAMES = (config.COOKIE_TOKEN_NAME, config.COOKIE_EXPIRE_NAME)
TOKEN_TEXT_RE = re.compile(r"[0-9a-f]{64}")


def mask_token(tok) -> str:
    return f"{tok[:6]}..." if tok else "None"


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def normalize_expire_ms(raw) -> int:
    """lastLoginTime 原始字串 → 毫秒。10 位數視為秒（×1000），13 位數視為毫秒。"""
    s = raw.decode("ascii") if isinstance(raw, bytes) else str(raw)
    if not re.fullmatch(r"\d{10,13}", s):
        raise ValueError("lastLoginTime 格式錯誤")
    value = int(s)
    return value * 1000 if len(s) == 10 else value


# token 與到期時間同屬一份 document.cookie 字串，彼此相鄰；只在 token 附近找到期時間
EXPIRE_NEAR_BYTES = 4096


def extract_from_bytes(data: bytes) -> Optional[TokenInfo]:
    """從一段記憶體/文字中找 token 與到期時間。找不到 token 回 None。"""
    m = TOKEN_RE.search(data)
    if not m:
        return None
    lo = max(0, m.start() - EXPIRE_NEAR_BYTES)
    hi = m.end() + EXPIRE_NEAR_BYTES
    em = EXPIRE_RE.search(data, lo, hi)
    expire = None
    if em:
        try:
            expire = normalize_expire_ms(em.group(1))
        except ValueError:
            expire = None
    return TokenInfo(m.group(1).decode("ascii"), expire, "memory")


# ---------------------------------------------------------------------------
# 1) 記憶體掃描（Tappo 執行中）
# ---------------------------------------------------------------------------
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
PAGE_GUARD = 0x100
READABLE_MASK = 0xEE  # 允許讀取的記憶體保護旗標遮罩

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
_k32.VirtualQueryEx.restype = ctypes.c_size_t
_k32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
]
_k32.ReadProcessMemory.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.LocalFree.argtypes = [ctypes.c_void_p]


class MBI(ctypes.Structure):
    # 與 Windows MEMORY_BASIC_INFORMATION 一致（含 PartitionId，64 位元必需）
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


def _renderer_pids():
    pids = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if (p.info["name"] or "").lower() != config.WEBVIEW_PROCESS.lower():
                continue
            args = p.info["cmdline"] or []
        except (psutil.Error, KeyError):
            continue
        if config.PROCESS_CMDLINE_MATCH in " ".join(args).lower() and "--type=renderer" in args:
            pids.append(p.info["pid"])
    return pids


# 分塊讀取，避免一次配置整個大區塊造成記憶體峰值。
# overlap 需 >= token 片語長度 + 到期時間搜尋範圍，確保跨塊邊界的 token/到期仍能成對找到。
CHUNK_BYTES = 4 * 1024 * 1024
CHUNK_OVERLAP = EXPIRE_NEAR_BYTES + 256


def chunk_offsets(size: int, chunk: int = CHUNK_BYTES, overlap: int = CHUNK_OVERLAP):
    """產生 (offset, want) 分塊；相鄰塊重疊 overlap。純函式，保證終止。"""
    if size <= 0:
        return
    step = max(1, chunk - overlap)
    off = 0
    while off < size:
        want = min(chunk, size - off)
        yield off, want
        if want < chunk:
            return
        off += step


def _scan_region(h, base: int, size: int) -> Optional[TokenInfo]:
    buf = ctypes.create_string_buffer(min(size, CHUNK_BYTES))
    n = ctypes.c_size_t()
    for off, want in chunk_offsets(size):
        if not (_k32.ReadProcessMemory(h, ctypes.c_void_p(base + off), buf, want, ctypes.byref(n)) and n.value):
            break
        info = extract_from_bytes(buf.raw[: n.value])
        if info:
            return info
        if n.value < want:
            break
    return None


def scan_pid(pid: int) -> Optional[TokenInfo]:
    h = _k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return None
    try:
        mbi = MBI()
        addr = 0
        while True:
            if not _k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            base = mbi.BaseAddress or 0
            size = mbi.RegionSize
            if size == 0:
                break
            if (mbi.State == MEM_COMMIT and mbi.Type == MEM_PRIVATE
                    and (mbi.Protect & READABLE_MASK) and not (mbi.Protect & PAGE_GUARD)):
                info = _scan_region(h, base, size)
                if info:
                    return info
            addr = base + size
        return None
    finally:
        _k32.CloseHandle(h)


def read_from_memory() -> Optional[TokenInfo]:
    for pid in _renderer_pids():
        try:
            info = scan_pid(pid)
        except Exception as e:  # 單一程序失敗不影響其他程序
            log.debug("scan pid failed: %s", type(e).__name__)
            continue
        if info:
            return info
    return None


# ---------------------------------------------------------------------------
# 2) Cookie 檔（Tappo 未執行）
# ---------------------------------------------------------------------------
class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def dpapi_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    buf = ctypes.create_string_buffer(data, len(data))  # 需保持存活直到呼叫結束
    inp = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _DataBlob()
    if not crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _k32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def dpapi_protect(data: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    buf = ctypes.create_string_buffer(data, len(data))
    inp = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _DataBlob()
    if not crypt32.CryptProtectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _k32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def webview_dir() -> str:
    return config.webview_dir()


def load_cookie_key(local_state_path: str) -> bytes:
    with open(local_state_path, "r", encoding="utf-8") as f:
        ls = json.load(f)
    enc = base64.b64decode(ls["os_crypt"]["encrypted_key"])
    if not enc.startswith(b"DPAPI"):
        raise RuntimeError("cookie 金鑰格式不是 DPAPI（可能是 App-Bound 加密）")
    return dpapi_unprotect(enc[5:])


def decrypt_cookie_value(encrypted: bytes, key: bytes, host_key: Optional[str] = None) -> str:
    """解密 v10/v11 cookie（AES-256-GCM）；新版 Chromium 明文前綴多 32 bytes，用 host_key 判斷去除。"""
    if encrypted[:3] not in (b"v10", b"v11"):
        raise ValueError("未知的 cookie 加密前綴")
    plain = AESGCM(key).decrypt(encrypted[3:15], encrypted[15:], None)
    if host_key is not None:
        if plain[:32] == hashlib.sha256(host_key.encode("utf-8")).digest():
            plain = plain[32:]
        return plain.decode("utf-8")
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError:
        return plain[32:].decode("utf-8")


def read_from_cookie_file() -> Optional[TokenInfo]:
    base = webview_dir()
    src = os.path.join(base, "Default", "Network", "Cookies")
    local_state = os.path.join(base, "Local State")
    if not (os.path.isfile(src) and os.path.isfile(local_state)):
        return None
    key = load_cookie_key(local_state)

    # 複製到專案資料夾內的暫存目錄（不寫入 C:\ 暫存區），用完即刪
    with tempfile.TemporaryDirectory(prefix="cookie_", dir=APP_DIR) as tmp:
        dst = os.path.join(tmp, "Cookies")
        try:
            shutil.copyfile(src, dst)
        except OSError:
            return None  # Tappo 執行中會獨占鎖定，讀不到就跳過
        con = sqlite3.connect(Path(dst).as_uri() + "?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT name, host_key, value, encrypted_value FROM cookies WHERE name IN (?, ?)",
                COOKIE_NAMES,
            ).fetchall()
        finally:
            con.close()

    values = {}
    for name, host_key, plain, enc in rows:
        if name in values:
            continue
        if plain:
            values[name] = plain
        elif enc:
            try:
                values[name] = decrypt_cookie_value(bytes(enc), key, host_key)
            except Exception as e:
                log.warning("cookie %s 解密失敗: %s", name, type(e).__name__)

    tok = values.get(config.COOKIE_TOKEN_NAME)
    if not tok or not TOKEN_TEXT_RE.fullmatch(tok):
        return None
    expire = None
    raw_exp = values.get(config.COOKIE_EXPIRE_NAME)
    if raw_exp:
        try:
            expire = normalize_expire_ms(raw_exp)
        except ValueError:
            expire = None
    return TokenInfo(tok, expire, "cookie")


# ---------------------------------------------------------------------------
# 快取
# ---------------------------------------------------------------------------
def load_cache() -> Optional[TokenInfo]:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    tok = None
    enc = d.get("token_enc")
    if isinstance(enc, str):
        try:
            tok = dpapi_unprotect(base64.b64decode(enc)).decode("ascii")
        except Exception:
            tok = None
    if tok is None:
        tok = d.get("token")
    exp = d.get("expire_ms")
    if not isinstance(tok, str) or not TOKEN_TEXT_RE.fullmatch(tok):
        return None
    if not isinstance(exp, int):
        exp = None
    if exp is not None and exp <= int(time.time() * 1000):
        return None
    return TokenInfo(tok, exp, "cache")


def save_cache(token: str, expire_ms: Optional[int]) -> None:
    payload = {"expire_ms": expire_ms}
    try:
        payload["token_enc"] = base64.b64encode(dpapi_protect(token.encode("ascii"))).decode("ascii")
    except Exception:
        payload["token"] = token
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except OSError as e:
        log.warning("寫入 token 快取失敗: %s", type(e).__name__)


# ---------------------------------------------------------------------------
# 對外入口
# ---------------------------------------------------------------------------
def get_token(fresh: bool = False) -> Optional[TokenInfo]:
    """fresh=True 略過快取（用於 token 失效後重讀、或使用者按「重新偵測」）。"""
    if not fresh:
        cached = load_cache()
        if cached:
            return cached
    for label, reader in (("記憶體", read_from_memory), ("Cookie 檔", read_from_cookie_file)):
        try:
            info = reader()
        except Exception as e:
            log.warning("%s 讀取失敗: %s", label, type(e).__name__)
            continue
        if info:
            save_cache(info.token, info.expire_ms)
            return info
    return None
