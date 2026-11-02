"""一鍵打包成單檔 exe（Windows）：自動建置前端再 PyInstaller，輸出 dist\\WuwaTappoAuto.exe。"""

import os
import subprocess
import sys

import config

NAME = f"WuwaTappoAuto-v{config.APP_VERSION}"
ENTRY = "app.py"
FIRST_PARTY = (
    "api", "scheduler", "core", "history", "i18n",
    "config", "click_store", "token_reader", "rewards", "names",
)


def build_frontend(root):
    """建置前端（web/）。npm 不存在時，若已有 web/dist 則沿用，否則中止。"""
    web = os.path.join(root, "web")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    import shutil
    if shutil.which(npm) is None and shutil.which("npm") is None:
        if os.path.isfile(os.path.join(web, "dist", "index.html")):
            print("找不到 npm，沿用現有 web/dist")
            return
        print("找不到 npm，且無 web/dist，無法建置前端。請先安裝 Node.js。")
        sys.exit(1)
    npm = npm if shutil.which(npm) else "npm"
    if not os.path.isdir(os.path.join(web, "node_modules")):
        print("安裝前端相依（npm install）…")
        subprocess.check_call([npm, "install"], cwd=web)
    print("建置前端（npm run build）…")
    subprocess.check_call([npm, "run", "build"], cwd=web)


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    build_frontend(root)
    dist_web = os.path.join(root, "web", "dist", "index.html")
    if not os.path.isfile(dist_web):
        print("前端建置後仍找不到 web/dist/index.html，請檢查 web/ 專案。")
        sys.exit(1)
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("安裝 pyinstaller…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    sep = os.pathsep
    args = [
        sys.executable, "-m", "PyInstaller",
        os.path.join(root, ENTRY),
        "--onefile",
        "--windowed",
        "--name", NAME,
        "--clean",
        "--noconfirm",
        # 讓 PyInstaller 能從專案根找到第一方模組
        "--paths", root,
        # 前端靜態檔（由 app.py 以本機伺服器提供，透過 config.resource_path 讀取）
        "--add-data", os.path.join(root, "web", "dist") + sep + os.path.join("web", "dist"),
        # 系統匣圖示
        "--add-data", os.path.join(root, "assets", "app.png") + sep + "assets",
        # pywebview（含 WebView2 後端與注入 JS）與 pythonnet 載入器
        "--collect-all", "webview",
        "--collect-all", "clr_loader",
        "--hidden-import", "pystray._win32",
    ]
    for mod in FIRST_PARTY:   # 強制收錄全部第一方模組（含延遲 import 者）
        args += ["--hidden-import", mod]
    icon = os.path.join(root, "assets", "app.ico")
    if os.path.isfile(icon):
        args += ["--icon", icon]

    print("打包中…")
    subprocess.check_call(args, cwd=root)
    print(f"\n完成：{os.path.join(root, 'dist', NAME + '.exe')}")


if __name__ == "__main__":
    main()
