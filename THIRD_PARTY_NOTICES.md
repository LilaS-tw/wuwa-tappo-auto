# Third-Party Notices

This product bundles the following third-party open-source software. Each component
remains under its own license; the full license text is distributed with each package
(and available at its project page). SPDX identifiers are listed for reference.

## Runtime — Python backend (bundled into the packaged executable)

| Package | License (SPDX) | Project |
| --- | --- | --- |
| requests | Apache-2.0 | https://github.com/psf/requests |
| psutil | BSD-3-Clause | https://github.com/giampaolo/psutil |
| cryptography | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| pywebview | BSD-3-Clause | https://github.com/r0x0r/pywebview |
| pystray | LGPL-3.0-only | https://github.com/moses-palmer/pystray |
| Pillow | HPND | https://github.com/python-pillow/Pillow |
| pythonnet | MIT | https://github.com/pythonnet/pythonnet |
| clr-loader | MIT | https://github.com/pythonnet/clr-loader |

## Runtime — Web frontend (bundled into the built JavaScript)

| Package | License (SPDX) | Project |
| --- | --- | --- |
| react | MIT | https://github.com/facebook/react |
| react-dom | MIT | https://github.com/facebook/react |
| antd | MIT | https://github.com/ant-design/ant-design |
| @ant-design/icons | MIT | https://github.com/ant-design/ant-design-icons |

## Build-time only (not distributed in the product)

| Package | License (SPDX) | Project |
| --- | --- | --- |
| PyInstaller | GPL-2.0-or-later WITH a special bootloader exception | https://github.com/pyinstaller/pyinstaller |
| vite | MIT | https://github.com/vitejs/vite |
| @vitejs/plugin-react | MIT | https://github.com/vitejs/vite-plugin-react |
| oxlint | MIT | https://github.com/oxc-project/oxc |

## Notes

- **pystray** is used unmodified under the GNU LGPL v3. The library is obtained from PyPI
  as-is; its source is available at the project page above, and it can be replaced with a
  compatible version by the end user.
- **PyInstaller** is a build tool. Its bootloader, embedded in the packaged executable, is
  distributed under PyInstaller's GPL-2.0-or-later license together with the official
  bootloader exception, which permits bundling and distributing applications under the
  application's own license.
- The game assets, names and trademarks shown by this tool are the property of
  KURO GAMES and are not covered by this notice.
