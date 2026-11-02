// 橋接 pywebview：window.pywebview.api 由 Python 注入（可能稍晚於頁面載入）。
const ready = () =>
  !!(window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_state === 'function')

export function onReady(cb) {
  if (ready()) { cb(); return }
  const iv = setInterval(() => { if (ready()) { clearInterval(iv); cb() } }, 50)
  window.addEventListener('pywebviewready', () => { if (ready()) { clearInterval(iv); cb() } }, { once: true })
}

const call = (name, ...args) => {
  try {
    const fn = window.pywebview && window.pywebview.api && window.pywebview.api[name]
    return typeof fn === 'function' ? fn(...args) : Promise.reject(new Error('api not ready: ' + name))
  } catch (e) {
    return Promise.reject(e)
  }
}

export const api = {
  getState: () => call('get_state'),
  openChest: (p) => call('open_chest', p),
  setAuto: (on) => call('set_auto', on),
  redetect: () => call('redetect'),
  syncNow: () => call('sync_now'),
  setAppearance: (m) => call('set_appearance', m),
  setLocale: (c) => call('set_locale', c),
  openLog: () => call('open_log'),
  setTray: (on) => call('set_tray', on),
  minimize: () => call('minimize_window'),
  close: () => call('close_window'),
  startDrag: () => call('start_drag'),
}
