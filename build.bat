@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Wuwa Tappo 自動寶箱 打包 ===
python build.py
if errorlevel 1 (
  echo.
  echo 打包失敗，請確認已安裝 Python。
)
pause
