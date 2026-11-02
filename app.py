"""進入點：啟動 scheduler、本機 HTTP 伺服器與 pywebview 視窗。"""

import json
import logging
import logging.handlers
import os
import queue
import threading
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import webview

import api as api_mod
import click_store
import config
import core
import i18n
import rewards
import token_reader
from scheduler import ChestScheduler

try:
    import pystray
    from PIL import Image
    TRAY_AVAILABLE = True
except Exception:
    pystray = None
    Image = None
    TRAY_AVAILABLE = False

DIST = config.resource_path(os.path.join("web", "dist"))


def setup_logging():
    path = os.path.join(config.data_dir(), "app.log")
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


# ---------------------------------------------------------------------------
# 本機靜態伺服器：/ -> web/dist；/img/<name> -> 獎勵圖快取
# ---------------------------------------------------------------------------
def make_handler():
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=DIST, **k)

        def _host_ok(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost", "")

        def do_GET(self):
            if not self._host_ok():
                self.send_error(403)
                return
            super().do_GET()

        def do_HEAD(self):
            if not self._host_ok():
                self.send_error(403)
                return
            super().do_HEAD()

        def translate_path(self, path):
            p = urllib.parse.urlparse(path).path
            if p.startswith("/img/"):
                return os.path.join(rewards.CACHE_DIR, os.path.basename(p))
            return super().translate_path(path)

        def log_message(self, *a):
            pass

    return Handler


def window_geometry():
    default = (1040, 720, None, None)
    if os.name != "nt":
        return default
    try:
        import ctypes
        from ctypes import wintypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem() or 96
        except Exception:
            dpi = 96
        scale = dpi / 96.0
        lw, lh = (rect.right - rect.left) / scale, (rect.bottom - rect.top) / scale
        lx, ly = rect.left / scale, rect.top / scale
        w = int(max(960, min(1280, lw * 0.82)))
        h = int(max(640, min(860, lh * 0.88)))
        return w, h, int(lx + (lw - w) / 2), int(ly + (lh - h) / 2)
    except Exception:
        return default


def _system_dark():
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except Exception:
        return True


def window_bg(appearance):
    dark = appearance == "dark" or (appearance == "system" and _system_dark())
    return "#1B1B1F" if dark else "#F0F2F5"


def _own_hwnd():
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    pid = ctypes.windll.kernel32.GetCurrentProcessId()
    result = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            result.append(hwnd)
            return False
        return True

    user32.EnumWindows(_cb, 0)
    return result[0] if result else None


def enable_taskbar_minimize():
    hwnd = _own_hwnd()
    if not hwnd:
        return
    import ctypes
    user32 = ctypes.windll.user32
    GWL_STYLE = -16
    WS_SYSMENU = 0x00080000
    WS_MINIMIZEBOX = 0x00020000
    SWP = 0x0001 | 0x0002 | 0x0004 | 0x0020  # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_SYSMENU | WS_MINIMIZEBOX)
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP)


def start_server() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler())
    threading.Thread(target=server.serve_forever, daemon=True, name="http").start()
    return server.server_address[1]


# ---------------------------------------------------------------------------
# 系統匣
# ---------------------------------------------------------------------------
class Tray:
    def __init__(self, window, title, on_quit=None):
        self._window = window
        self._title = title
        self._icon = None
        self._on_quit = on_quit

    def _image(self):
        try:
            return Image.open(config.resource_path(os.path.join("assets", "app.png")))
        except Exception:
            return Image.new("RGBA", (64, 64), (31, 106, 192, 255))

    def show(self):
        if not TRAY_AVAILABLE or self._icon is not None:
            return
        menu = pystray.Menu(
            pystray.MenuItem(i18n.t("tray_show"), lambda *_: self._restore(), default=True),
            pystray.MenuItem(i18n.t("tray_quit"), lambda *_: self._quit()),
        )
        self._icon = pystray.Icon("wuwa_tappo_auto", self._image(), self._title, menu)
        threading.Thread(target=self._icon.run, daemon=True, name="tray-icon").start()

    def stop(self):
        icon, self._icon = self._icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass

    def _restore(self):
        self.stop()
        try:
            self._window.show()
        except Exception:
            pass

    def _quit(self):
        self.stop()
        if self._on_quit is not None:
            self._on_quit()
        try:
            self._window.destroy()
        except Exception:
            pass


def main():
    setup_logging()
    settings = api_mod.load_settings()
    i18n.set_locale(settings["locale"])

    scheduler = ChestScheduler(
        core.TappoApi(),
        token_reader.get_token,
        on_token=token_reader.save_cache,
        auto_enabled=settings["auto"],
        click_source=click_store.ClickFile(),
        history_path=config.history_path(),
    )

    state = {"window": None, "tray": None, "quitting": False}

    def on_set_tray(on):
        if not on and state["tray"] is not None:
            state["tray"].stop()

    api = api_mod.Api(scheduler, settings, tray_available=TRAY_AVAILABLE, on_set_tray=on_set_tray)

    port = start_server()
    title = i18n.t("app_title")
    w, h, x, y = window_geometry()
    kw = dict(width=w, height=h, min_size=(900, 620),
              frameless=True, easy_drag=False,
              background_color=window_bg(settings["appearance"]))
    if x is not None:
        kw.update(x=x, y=y)
    window = webview.create_window(title, f"http://127.0.0.1:{port}/", js_api=api, **kw)
    state["window"] = window

    def request_quit():
        state["quitting"] = True

    tray = Tray(window, title, on_quit=request_quit)
    state["tray"] = tray

    def on_closing():
        if state["quitting"]:
            return True
        if settings.get("tray") and TRAY_AVAILABLE:
            window.hide()
            tray.show()
            return False
        return True

    window.events.closing += on_closing
    if os.name == "nt":
        window.events.shown += lambda: enable_taskbar_minimize()

    def do_minimize():
        try:
            window.minimize()
        except Exception:
            pass

    def do_close():
        if settings.get("tray") and TRAY_AVAILABLE:
            window.hide()
            tray.show()
        else:
            state["quitting"] = True
            try:
                window.destroy()
            except Exception:
                pass

    def do_start_drag():
        if os.name != "nt":
            return
        try:
            import ctypes
            hwnd = _own_hwnd() or ctypes.windll.user32.GetForegroundWindow()
            if hwnd:
                ctypes.windll.user32.ReleaseCapture()
                ctypes.windll.user32.SendMessageW(hwnd, 0x00A1, 0x0002, 0)  # WM_NCLBUTTONDOWN, HTCAPTION
        except Exception:
            pass

    api.on_minimize = do_minimize
    api.on_close = do_close
    api.on_start_drag = do_start_drag

    stop_event = threading.Event()

    def worker():
        try:
            scheduler.run(stop_event)
        except Exception:
            logging.getLogger(__name__).exception("scheduler crashed")

    threading.Thread(target=worker, daemon=True, name="chest-scheduler").start()

    # 事件推送：後端狀態變更（scheduler._emit）主動推送前端
    loaded = threading.Event()
    window.events.loaded += lambda: loaded.set()

    def pusher():
        loaded.wait(timeout=30)
        while not stop_event.is_set():
            try:
                scheduler.events.get(timeout=0.5)
            except queue.Empty:
                continue
            try:                       # 合併佇列中其餘事件，只推一次最新狀態
                while True:
                    scheduler.events.get_nowait()
            except queue.Empty:
                pass
            try:
                state = api.get_state()
                window.evaluate_js("window.__pushState && window.__pushState(" +
                                   json.dumps(state, ensure_ascii=False) + ")")
            except Exception:
                pass

    threading.Thread(target=pusher, daemon=True, name="pusher").start()

    try:
        webview.start()
    finally:
        stop_event.set()
        tray.stop()


if __name__ == "__main__":
    main()
