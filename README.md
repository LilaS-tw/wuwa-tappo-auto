繁體中文 · [English](README.en.md)

# Wuwa Tappo Auto v1.0.0

冷卻結束自動開啟寶箱，維持原本官方程式。
(雖然叫做Auto，但沒有自動點擊功能)

## 功能

- 無須任何設定，開箱即用。
- 右側保留最近 60 筆獲得紀錄，保持和官方圖示、名稱、稀有度一致，可依角色／配件／表情篩選。
- 關閉官方 Tappo 程式也能自動開啟寶箱，但點擊數要累積夠多。

## 需求與限制

- 僅支援 Windows x64。
- 僅支援**Tappo Global**；相關設定請見 `config.py`。
- 至少要登入過一次 Tappo。
- 點擊數是由官方 Tappo 自己固定時間回報給伺服器。因此只有在「點擊剛好補足到開箱門檻」的邊界情況，最多可能慢約 30 秒才開；若點擊數遠超過需求，則會直接開啟。

## 安裝與執行（原始碼）

需要 Python 3.10+ 與 Node.js 20.19+：

```
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
python app.py
```

## 打包成單一執行檔

雙擊 `build.bat`（或執行 `python build.py`）即可自動建置前端並打包成單檔 `dist\WuwaTappoAuto.exe`，雙擊就能直接運行，不必安裝 Python。

打包版的 token 快取／設定／日誌／圖片快取會寫到 `%LOCALAPPDATA%\WuwaTappoAuto\`（若從原始碼執行，則寫入當前資料夾）。

## 隱私

- Token 只用來呼叫官方 API，不會上傳任何第三方，日誌只留前 6 碼。
- Token 加密後快取在 `token_cache.json`。
- `app.log` 只記錄事件與錯誤。

## 免責聲明

本工具為非官方的第三方工具，與庫洛遊戲（KURO GAMES）及《鳴潮》、「Wuwa Tappo」官方並無任何關聯，亦未經其認可或授權。《鳴潮》、「Wuwa Tappo」及其所有遊戲內素材、名稱與商標之著作權與相關權利，均歸庫洛遊戲（KURO GAMES）所有。本工具依「現狀」提供、不負任何擔保，使用之風險由使用者自行承擔。

## 授權

MIT License，見 [LICENSE](LICENSE)。第三方開源套件的授權見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
