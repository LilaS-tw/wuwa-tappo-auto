"""寶箱排程（純邏輯，不含 GUI）：啟動取冷卻時間，背景每秒本機比對，到點且點擊足夠即開箱。
run() 跑在背景執行緒，外部透過 post() 送指令、events 佇列收快照與日誌。"""

import logging
import queue
import threading
import time
import traceback
from typing import Callable, Optional

log = logging.getLogger(__name__)

import core
import history
import i18n
import names
from core import ApiError, AuthError, NetworkError, NotEnoughClicks
from i18n import t

PLACES = ("left", "right")
# API 的 left = 下寶箱、right = 上寶箱
PLACE_LABEL_KEY = {"left": "chest_bottom", "right": "chest_top"}
DISPLAY_ORDER = ("right", "left")

def place_name(place: str) -> str:
    """寶箱名稱（依目前語言）。"""
    return t(PLACE_LABEL_KEY[place])

ARRIVAL_MARGIN_MS = 1500
DEFAULT_CHEST_COST = 1000
NETWORK_RETRY_MS = 30 * 1000
MAX_FAILURES = 3

RENEW_THRESHOLD_MS = 2 * 24 * 3600 * 1000
RENEW_EXTEND_MS = 7 * 24 * 3600 * 1000
RENEW_RETRY_MS = 60 * 60 * 1000
REBOOTSTRAP_MS = 30 * 1000


class _Stopped(Exception):
    """內部用：認證失敗且無法恢復，自動開箱已停止。"""


def _mask(tok: Optional[str]) -> str:
    return f"{tok[:6]}..." if tok else "None"


class ChestScheduler:
    def __init__(
        self,
        api,
        token_provider: Callable[[bool], object],
        clock_ms: Callable[[], int] = core.now_ms,
        on_token: Optional[Callable[[str, Optional[int]], None]] = None,
        auto_enabled: bool = False,
        click_source: Optional[Callable[[], object]] = None,
        history_path: Optional[str] = None,
    ):
        self.api = api
        self._provider = token_provider
        self._clock = clock_ms
        self._on_token = on_token or (lambda token, expire_ms: None)
        self._click_source = click_source or (lambda: None)
        self.cuid: Optional[str] = None
        self.chest_cost = DEFAULT_CHEST_COST
        self._waiting_clicks = {p: False for p in PLACES}
        self.assets_host: Optional[str] = None            # 獎勵圖 CDN base
        self.catalog = None                                # 資產目錄
        self._history_path = history_path
        self.history: list = history.load(history_path) if history_path else []   # 最近獲得（舊 -> 新）

        self.events: "queue.Queue" = queue.Queue()
        self.commands: "queue.Queue" = queue.Queue()
        self._names_lock = threading.Lock()      # 字典下載同時只跑一條執行緒
        self._names_thread: Optional[threading.Thread] = None

        self.token: Optional[str] = None
        self.expire_ms: Optional[int] = None
        self.nickname: Optional[str] = None
        self.total_click_count: Optional[int] = None
        self.total_click_consume: Optional[int] = None
        self.due = {p: None for p in PLACES}          # 伺服器時間（毫秒）
        self.failures = {p: 0 for p in PLACES}
        self.paused = {p: False for p in PLACES}

        self.auto_enabled = bool(auto_enabled)
        self.auth_stopped = False
        self._renew_next_ms = 0
        self._bootstrap_next_ms = 0

    # ------------------------------------------------------------------
    # 時間
    # ------------------------------------------------------------------
    def offset_ms(self) -> int:
        return int(getattr(self.api, "offset_ms", 0) or 0)

    def server_now(self) -> int:
        return self._clock() + self.offset_ms()

    # ------------------------------------------------------------------
    # 事件輸出（給 GUI）
    # ------------------------------------------------------------------
    def _log(self, msg: str) -> None:
        log.info(msg)
        self.events.put(("log", f"[{time.strftime('%H:%M:%S')}] {msg}"))

    def _emit(self) -> None:
        self.events.put(("snapshot", self.snapshot()))

    def snapshot(self) -> dict:
        if self.auth_stopped:
            status = "auth"
        elif not self.token:
            status = "no_token"
        elif self.nickname:
            status = "connected"
        else:
            status = "pending"
        return {
            "status": status,
            "auto": self.auto_enabled,
            "auth_stopped": self.auth_stopped,
            "token_hint": _mask(self.token) if self.token else None,
            "expire_ms": self.expire_ms,
            "nickname": self.nickname,
            "total_click_count": self.total_click_count,
            "total_click_consume": self.total_click_consume,
            "due": dict(self.due),
            "paused": dict(self.paused),
            "failures": dict(self.failures),
            "offset_ms": self.offset_ms(),
            "clock_ms": self._clock(),
            "history": [dict(e) for e in self.history],
        }

    # ------------------------------------------------------------------
    # Token
    # ------------------------------------------------------------------
    def _adopt(self, info) -> None:
        self.token = info.token
        self.expire_ms = info.expire_ms
        self._on_token(info.token, info.expire_ms)
        src = t(f"source_{info.source}") if i18n.CATALOG["en"].get(f"source_{info.source}") else info.source
        self._log(t("log_got_token", mask=_mask(info.token), source=src))
        if info.expire_ms:
            log.info("token adopted (source=%s): expiry in %.1f days",
                     info.source, (info.expire_ms - self._clock()) / 86400000.0)
        else:
            log.info("token adopted (source=%s): expiry unknown", info.source)

    def _reread_fresh(self):
        try:
            return self._provider(True)
        except Exception as e:
            self._log(t("log_reread_token_failed", err=type(e).__name__))
            return None

    def bootstrap(self, fresh: bool = False) -> bool:
        try:
            info = self._provider(fresh)
        except Exception as e:
            self._log(t("log_read_token_failed", err=type(e).__name__))
            info = None
        if not info:
            self._log(t("log_no_token"))
            self._emit()
            return False
        self._adopt(info)
        return self.sync()

    def _stop_for_auth(self) -> None:
        if self.expire_ms:
            log.info("auth stop: token already expired=%s (expire_ms=%d, now=%d)",
                     self._clock() >= self.expire_ms, self.expire_ms, self._clock())
        else:
            log.info("auth stop: token expiry unknown")
        self.auto_enabled = False
        self.auth_stopped = True
        self._log(t("log_auth_stopped"))
        self._emit()

    def _call(self, fn):
        """以目前 token 呼叫 fn(token)。AuthError 時重讀 token，只有不同才重試一次。"""
        try:
            return fn(self.token)
        except AuthError as e:
            self._log(t("log_token_invalid_reread", err=e))
        fresh = self._reread_fresh()
        if fresh is not None and fresh.token != self.token:
            self._adopt(fresh)
            try:
                return fn(self.token)
            except AuthError:
                pass
        self._stop_for_auth()
        raise _Stopped()

    # ------------------------------------------------------------------
    # 同步 / 開箱
    # ------------------------------------------------------------------
    def _local_clicks(self) -> Optional[int]:
        """本機點擊檔的 count（帳號不符或讀不到時為 None）。順便更新顯示用總點擊數。"""
        state = self._click_source()
        if state is None or (self.cuid and state.cuid and state.cuid != self.cuid):
            return None
        if self.total_click_count is None or state.count > self.total_click_count:
            self.total_click_count = state.count
        return state.count

    def _available(self) -> Optional[int]:
        count = self._local_clicks()
        if count is None or self.total_click_consume is None:
            return None
        return count - self.total_click_consume

    def _apply_me(self, me: core.UserMe, apply: tuple) -> None:
        self.nickname = me.nickname or self.nickname
        self.cuid = getattr(me, "cuid", None) or self.cuid
        self.total_click_count = me.total_click_count
        self.total_click_consume = me.total_click_consume
        if "left" in apply and me.left_ms is not None:
            self.due["left"] = me.left_ms
        if "right" in apply and me.right_ms is not None:
            self.due["right"] = me.right_ms

    def sync(self, apply: tuple = PLACES) -> bool:
        """呼叫 1 次 /user/me。apply 指定要用哪些寶箱的冷卻來校正 due。"""
        if not self.token:
            return False
        try:
            me = self._call(lambda tok: self.api.get_user_me(tok))
        except _Stopped:
            return False
        except NetworkError as e:
            self._log(t("log_sync_failed_net", err=e))
            self._emit()
            return False
        except ApiError as e:
            self._log(t("log_sync_failed", err=e))
            self._emit()
            return False
        self._apply_me(me, apply)
        self._log(t("log_sync_done", clicks=me.total_click_count))
        self._emit()
        return True

    def _fetch_reward_image(self, res) -> Optional[str]:
        """在背景執行緒用目錄 + asset_id 下載並快取獎勵真圖；失敗回 None（UI 退回名稱）。"""
        try:
            import rewards
            if self.assets_host is None:
                self.assets_host = self.api.get_assets_host()
            if self.catalog is None and self.assets_host:
                self.catalog = self.api.get_appearance_catalog(self.assets_host)
            return rewards.ensure_reward_image(self.assets_host, self.catalog, res.asset_type, res.asset_id)
        except Exception as e:
            self._log_debug(f"reward image failed: {type(e).__name__}")
            return None

    def _log_debug(self, msg: str) -> None:
        log.info(msg)

    # ------------------------------------------------------------------
    # 名稱字典
    # ------------------------------------------------------------------
    def _start_names_fetch(self) -> Optional[threading.Thread]:
        """啟動背景下載字典；已有下載中則略過（回 None）。不阻塞排程迴圈。"""
        if not self._names_lock.acquire(blocking=False):
            return None
        th = threading.Thread(target=self._fetch_names_worker, daemon=True, name="names-dict")
        self._names_thread = th
        try:
            th.start()
        except Exception:
            self._names_lock.release()
            raise
        return th

    def _fetch_names_worker(self) -> None:
        try:
            if self.assets_host is None:
                self.assets_host = self.api.get_assets_host()
            lang = names.dict_lang(i18n.get_locale())
            if names.ensure_dict(self.assets_host, lang) is not None:
                self.events.put(("names", lang))
        except Exception as e:
            self._log_debug(f"names dict failed: {type(e).__name__}")
        finally:
            self._names_lock.release()

    def _count_failure(self, place: str, resync: bool) -> None:
        self.failures[place] += 1
        if resync:
            self.sync(apply=PLACES)
        if self.failures[place] >= MAX_FAILURES and not self.paused[place]:
            self.paused[place] = True
            self._log(t("log_paused", place=place_name(place), count=self.failures[place]))
        self._emit()

    def _open(self, place: str) -> bool:
        name = place_name(place)
        click = self._local_clicks()
        if click is None:
            # 讀不到本機點擊檔：改用伺服器值，開箱前先同步（順便校正冷卻）
            if not self.sync(apply=(place,)) or self.total_click_count is None:
                return False
            due = self.due[place]
            if due is not None and self.server_now() < due:
                self._log(t("log_cooldown_not_over", place=name))
                self._emit()
                return False
            click = self.total_click_count
        self._log(t("log_open", place=name, click=click))
        try:
            res = self._call(lambda tok: self.api.open_chest(tok, place, click))
        except _Stopped:
            return False
        except NotEnoughClicks:
            # 已消耗數可能過時（例如:在 Tappo 手動開過）：校正 1 次，之後等點擊檔更新
            self.sync()
            self._waiting_clicks[place] = True
            self._log(t("log_not_enough_waiting", place=name))
            self._emit()
            return False
        except NetworkError as e:
            self.due[place] = self.server_now() + NETWORK_RETRY_MS
            self._log(t("log_open_failed_net", place=name, err=e))
            self._count_failure(place, resync=False)
            return False
        except ApiError as e:
            self._log(t("log_open_failed", place=name, err=e))
            self._count_failure(place, resync=True)
            return False

        # 成功：回應的 next_time 同時更新兩個寶箱
        self.failures[place] = 0
        self._waiting_clicks[place] = False
        self._fetch_reward_image(res)   # 背景下載圖片並快取
        self._record_history(res)
        if res.click_consume:
            self.chest_cost = res.click_consume
        if res.left_next_ms is not None:
            self.due["left"] = res.left_next_ms
        if res.right_next_ms is not None:
            self.due["right"] = res.right_next_ms
        self._log(t("log_open_success", place=name, reward=res.asset_name, rarity=res.rarity_type))
        if res.click_consume and self.total_click_consume is not None:
            self.total_click_consume += res.click_consume
        # 回應缺少的冷卻才從 /user/me 補上
        missing = tuple(p for p in PLACES if (res.left_next_ms if p == "left" else res.right_next_ms) is None)
        if missing:
            self.sync(apply=missing)
        self._emit()
        return True

    def _record_history(self, res) -> None:
        """開箱成功後附加到「最近獲得」並存檔（上限 60 筆）。"""
        history.append(self.history, history.make_entry(res, self._clock() // 1000))
        if self._history_path:
            history.save(self._history_path, self.history)

    def tick(self) -> None:
        if not self.auto_enabled or self.auth_stopped:
            return
        if not self.token:
            now = self._clock()
            if now >= self._bootstrap_next_ms:
                self._bootstrap_next_ms = now + REBOOTSTRAP_MS
                self.bootstrap()
            return
        try:
            self._maybe_renew()
        except _Stopped:
            return
        before = self.total_click_count
        available = self._available()
        if self.total_click_count != before:
            self._emit()
        for place in PLACES:
            if not self.auto_enabled or self.auth_stopped:
                return
            due = self.due[place]
            if self.paused[place] or due is None:
                continue
            if self.server_now() < due + ARRIVAL_MARGIN_MS:
                continue
            if available is None:
                if self._waiting_clicks[place]:
                    continue  # 讀不到點擊檔又曾點擊不足：等手動或下次同步
            elif available < self.chest_cost:
                if not self._waiting_clicks[place]:
                    self._waiting_clicks[place] = True
                    self._log(t("log_cooldown_over_not_enough", place=place_name(place),
                                available=available, cost=self.chest_cost))
                    self._emit()
                continue
            self._waiting_clicks[place] = False
            self._open(place)
            available = self._available()

    def open_now(self, place: str) -> None:
        self.paused[place] = False
        self.failures[place] = 0
        self._waiting_clicks[place] = False
        if not self.token and not self.bootstrap():
            return
        self._open(place)
        self._emit()

    # ------------------------------------------------------------------
    # 續期
    # ------------------------------------------------------------------
    def _maybe_renew(self) -> None:
        if not self.expire_ms:
            return
        now = self._clock()
        if self.expire_ms - now >= RENEW_THRESHOLD_MS or now < self._renew_next_ms:
            return
        self._renew_next_ms = now + RENEW_RETRY_MS
        try:
            ok = self._call(lambda tok: self.api.renew_token(tok))
        except (NetworkError, ApiError) as e:
            self._log(t("log_renew_failed", err=e))
            return
        if ok:
            self.expire_ms = now + RENEW_EXTEND_MS
            self._on_token(self.token, self.expire_ms)
            self._log(t("log_renewed"))
        else:
            self._log(t("log_renew_not_true"))

    # ------------------------------------------------------------------
    # 外部指令（GUI 執行緒 -> 背景執行緒）
    # ------------------------------------------------------------------
    def redetect(self) -> None:
        self.auth_stopped = False
        self.token = None
        self.nickname = None
        for p in PLACES:
            self.paused[p] = False
            self.failures[p] = 0
        self.bootstrap(fresh=True)

    def set_auto(self, on: bool) -> None:
        self.auto_enabled = bool(on)
        if on:
            self.auth_stopped = False
            for p in PLACES:
                self.paused[p] = False
                self.failures[p] = 0
            if self.token is None:
                self.bootstrap()
            else:
                self.sync()
        self._log(t("log_auto_on") if on else t("log_auto_off"))
        self._emit()

    def post(self, name: str, *args) -> None:
        self.commands.put((name, args))

    def _process_commands(self) -> None:
        while True:
            try:
                name, args = self.commands.get_nowait()
            except queue.Empty:
                return
            if name == "auto":
                self.set_auto(bool(args[0]))
            elif name == "sync":
                self.sync()
                self._emit()
            elif name == "open":
                self.open_now(args[0])
            elif name == "redetect":
                self.redetect()
            elif name == "ensure_dict":
                self._start_names_fetch()

    def run(self, stop_event, poll_s: float = 1.0) -> None:
        self._booted = False
        last_error_sig = None  # 避免同一個錯誤每秒洗版日誌
        while not stop_event.is_set():
            try:
                self._process_commands()
                if not self._booted:
                    self.bootstrap()   # 啟動同步也要受保護，否則非預期例外會讓整條執行緒死掉
                    self._booted = True
                    self._start_names_fetch()   # 字典在背景執行緒下載，不佔用排程迴圈
                else:
                    self.tick()
            except Exception as e:  # 背景執行緒不可因單次錯誤死掉
                tb = traceback.extract_tb(e.__traceback__)
                where = f"{tb[-1].name}:{tb[-1].lineno}" if tb else "?"
                sig = (type(e).__name__, where)
                # 完整堆疊寫到 log 檔（供回報），UI 日誌只在錯誤改變時記一行
                log.exception("background thread error @ %s", where)
                if sig != last_error_sig:
                    self._log(t("log_internal_error", err=type(e).__name__, where=where))
                    last_error_sig = sig
            self._emit()
            stop_event.wait(poll_s)
