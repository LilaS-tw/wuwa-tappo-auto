[繁體中文](README.md) · English

# Wuwa Tappo Auto v1.0.1

Automatically opens the two treasure chests when their cooldown ends, while you keep using the official app as usual.
(Despite the "Auto" name, there is no auto-clicking.)

## Features

- No setup — just open it and go.
- Keeps the last 60 rewards on the right, matching the official icons, names and rarity, filterable by character / accessory / emote.
- Works even when the official Tappo is closed, as long as you have enough accumulated clicks.

## Requirements & limitations

- Windows x64 only.
- Supports **Tappo Global** only; see `config.py` for configuration.
- You must have logged into Tappo at least once.
- Clicks are reported to the server by the official Tappo itself at a fixed interval. So only in the edge case where clicks *just* reach the open threshold may it be delayed by up to ~30s; if clicks far exceed the requirement, it opens immediately.

## Install & run (from source)

Requires Python 3.10+ and Node.js 20.19+:

```
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
python app.py
```

## Build a single executable

Double-click `build.bat` (or run `python build.py`) to build the frontend and package everything into a single `dist\WuwaTappoAuto.exe` that runs on double-click with no Python required.

In the packaged build, the token cache / settings / logs / image cache are written to `%LOCALAPPDATA%\WuwaTappoAuto\` (when run from source, they go to the current folder).

## Privacy

- The token is only used to call the official API; it is never uploaded to any third party, and logs keep only its first 6 characters.
- The token is cached encrypted in `token_cache.json`.
- `app.log` records only events and errors.

## Disclaimer

This is an unofficial, third-party tool. It is not affiliated with, endorsed by, or authorized by KURO GAMES or the official Wuthering Waves / "Wuwa Tappo". Wuthering Waves, "Wuwa Tappo", and all their in-game assets, names and trademarks are the property of KURO GAMES. This tool is provided "as is" without any warranty; use it at your own risk.

## License

MIT License — see [LICENSE](LICENSE). Third-party open-source licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
