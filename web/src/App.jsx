import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ConfigProvider, theme as antdTheme, Segmented, Select, Switch, Button,
  Empty, Spin,
} from 'antd'
import {
  ReloadOutlined, SyncOutlined, FileTextOutlined, GlobalOutlined,
  GiftOutlined,
} from '@ant-design/icons'
import { api, onReady } from './api.js'

import rarity1 from './assets/ui/rarity-1.png'
import rarity2 from './assets/ui/rarity-2.png'
import rarity3 from './assets/ui/rarity-3.png'
import rarity4 from './assets/ui/rarity-4.png'
import cardBg from './assets/ui/card-bg.png'
import typeCharacter from './assets/ui/type-character.png'
import typeAccessory from './assets/ui/type-accessory.png'
import typeEmote from './assets/ui/type-emote.png'

const RARITY_BG = { 1: rarity1, 2: rarity2, 3: rarity3, 4: rarity4 }
const RARITY_INDEX = { common: 1, uncommon: 2, rare: 3, epic: 4 }
const TYPE_ICON = { character_skin: typeCharacter, accessory: typeAccessory, emote: typeEmote }

const rarityBg = (r) => RARITY_BG[RARITY_INDEX[String(r || '').toLowerCase()] || 1]
const fmtClock = (ms) => {
  if (!ms) return ''
  const d = new Date(ms)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
const fmtRemain = (ms) => {
  const tot = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(tot / 3600), m = Math.floor((tot % 3600) / 60), s = tot % 60
  const p = (n) => String(n).padStart(2, '0')
  return h ? `${h}:${p(m)}:${p(s)}` : `${p(m)}:${p(s)}`
}

function HistoryCard({ item }) {
  const name = item.name || (item.assetName || '').replace(/\.png$/i, '')
  const ticon = TYPE_ICON[item.assetType]
  const nameRef = useRef(null)
  const onEnter = () => {
    const el = nameRef.current
    if (!el) return
    const inner = el.firstChild
    const overflow = inner.scrollWidth - inner.clientWidth
    if (overflow > 1) {
      el.style.setProperty('--mq', `-${overflow}px`)
      el.style.setProperty('--mqdur', `${Math.max(2, overflow / 40)}s`)
      el.classList.add('marquee')
    }
  }
  const onLeave = () => {
    const el = nameRef.current
    if (!el) return
    el.classList.remove('marquee')
    el.style.removeProperty('--mq')
    el.style.removeProperty('--mqdur')
  }
  return (
    <div className="hcard" style={{ backgroundImage: `url(${cardBg})` }}>
      <div className="hcard-panel" style={{ backgroundImage: `url(${rarityBg(item.rarityType)})` }}>
        {item.img
          ? <img className="hcard-reward" src={item.img} alt="" draggable={false} />
          : <span className="hcard-fallback">{name}</span>}
        {ticon && <img className="hcard-type" src={ticon} alt="" draggable={false} />}
      </div>
      <div className="hcard-name" ref={nameRef} title={name}
        onMouseEnter={onEnter} onMouseLeave={onLeave}><span>{name}</span></div>
    </div>
  )
}

function ChestCard({ chest, now, t, onOpen }) {
  const remain = chest.dueMs != null ? chest.dueMs - now : null
  const ready = remain != null && remain <= 0
  const paused = !!chest.paused
  const stateCls = chest.dueMs == null ? 'muted' : paused && ready ? 'err' : ready ? 'ok' : 'wait'
  const stateText = chest.dueMs == null
    ? t('chest_waiting_sync')
    : ready
      ? (paused ? t('chest_ready') + t('chest_paused_suffix') : t('chest_ready'))
      : fmtRemain(remain)
  return (
    <div className="panel chest">
      <div className="chest-title">{chest.label}</div>
      <div className={`chest-state ${stateCls}`}>{stateText}</div>
      {chest.dueMs != null && (
        <div className="chest-time">
          {t('chest_open_time').replace('{time}', fmtClock(chest.dueMs))}
        </div>
      )}
      <Button type="primary" disabled={!ready} className="chest-btn"
        onClick={() => onOpen(chest.place)}>{t('btn_open_now')}</Button>
    </div>
  )
}

export default function App() {
  const [st, setSt] = useState(null)
  const [now, setNow] = useState(Date.now())
  const [filter, setFilter] = useState('all')
  const sysDark = useRef(window.matchMedia?.('(prefers-color-scheme: dark)'))

  // 取狀態
  const refresh = () => api.getState().then(setSt).catch(() => {})
  // 先更新前端狀態，再送出請求並以後端回應校正，避免操作後畫面延遲
  const patchSettings = (p) => setSt((s) => (s ? { ...s, settings: { ...s.settings, ...p } } : s))
  const onAppearance = (mode) => { patchSettings({ appearance: mode }); api.setAppearance(mode).then(refresh).catch(() => {}) }
  const onLocale = (code) => { patchSettings({ locale: code }); api.setLocale(code).then(refresh).catch(() => {}) }
  const onAuto = (v) => { setSt((s) => ({ ...s, auto: v, settings: { ...s.settings, auto: v } })); api.setAuto(v).then(refresh).catch(() => {}) }
  const onTray = (v) => { patchSettings({ tray: v }); api.setTray(v).then(refresh).catch(() => {}) }
  useEffect(() => {
    window.__pushState = (s) => setSt(s)        // 後端狀態變更時主動推送至前端
    onReady(() => { refresh() })                // 初次載入時主動取得一次狀態
    const tick = setInterval(() => setNow(Date.now()), 500)  // 以本機時間倒數，不需連線
    return () => { clearInterval(tick); delete window.__pushState }
  }, [])

  const t = useMemo(() => {
    const dict = st?.i18n || {}
    return (k) => (dict[k] != null ? dict[k] : k)
  }, [st])

  const serverNow = now + (st?.offsetMs || 0)

  // 外觀：light / dark / system
  const appearance = st?.settings?.appearance || 'system'
  const isDark = appearance === 'dark' || (appearance === 'system' && (sysDark.current?.matches ?? true))

  if (!st) return (
    <div className="loading"><Spin size="large" /></div>
  )

  const statusText = {
    connected: st.nickname ? t('status_connected').replace('{nick}', st.nickname) : t('status_connected_noname'),
    auth: t('status_auth_failed'),
    no_token: t('status_no_token'),
    pending: t('status_detecting'),
  }[st.status] || t('status_detecting')

  const history = (st.history || []).filter((it) => filter === 'all' || it.assetType === filter)
  const empty = (v) => (v == null ? t('value_empty') : v)

  return (
    <ConfigProvider theme={{
      algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
      token: { colorPrimary: '#1f6ac0', borderRadius: 8 },
    }}>
      <div className={`shell ${isDark ? 'dark' : 'light'}`}>
        {/* 自訂標題列：標題列可拖曳移動視窗，右側為最小化／關閉鈕 */}
        <div className="titlebar">
          <div className="titlebar-drag"
            onMouseDown={(e) => { if (e.button === 0) api.startDrag() }}>
            <GiftOutlined className="tb-logo" />
            <span className="tb-title">{t('app_title')}</span>
            {st.version && <span className="tb-ver">v{st.version}</span>}
          </div>
          <div className="titlebar-ctrl">
            <button className="tb-btn" onClick={() => api.minimize()} aria-label="minimize">
              <span className="tb-min" />
            </button>
            <button className="tb-btn tb-close" onClick={() => api.close()} aria-label="close">
              <span className="tb-x">✕</span>
            </button>
          </div>
        </div>

        <div className="app">
        {/* 左欄 */}
        <div className="col left">
          <div className="panel">
            <div className="app-title">{t('app_title')}</div>
            <div className={`status s-${st.status}`}>{statusText}</div>
            <div className="statline">
              <span>{t('stat_clicks').replace('{value}', empty(st.totalClickCount))}</span>
              <span>{t('stat_consume').replace('{value}', empty(st.totalClickConsume))}</span>
            </div>
            <div className="row gap">
              <Button icon={<ReloadOutlined />} onClick={() => api.redetect()}>{t('btn_redetect')}</Button>
              <Button icon={<SyncOutlined />} onClick={() => api.syncNow()}>{t('btn_sync')}</Button>
              <Button icon={<FileTextOutlined />} onClick={() => api.openLog()}>{t('btn_open_log')}</Button>
            </div>
          </div>

          <div className="panel">
            <div className="row between">
              <div className="row gap">
                <Switch checked={!!st.auto} onChange={onAuto} />
                <span className="switch-label">{t('switch_auto')}</span>
              </div>
            </div>
            <div className={`hint ${st.authStopped ? 'err' : st.auto ? 'ok' : 'muted'}`}>
              {st.authStopped ? t('status_auth_failed') : st.auto ? t('hint_auto_on') : t('hint_auto_off')}
            </div>
            <div className="field">
              <span className="field-label">{t('appearance_label') || '外觀'}</span>
              <Segmented value={appearance} onChange={onAppearance}
                options={[
                  { label: t('appearance_light'), value: 'light' },
                  { label: t('appearance_dark'), value: 'dark' },
                  { label: t('appearance_system'), value: 'system' },
                ]} />
            </div>
            <div className="field">
              <span className="field-label"><GlobalOutlined /> {t('lang_label')}</span>
              <Select value={st.settings.locale} style={{ minWidth: 150 }}
                onChange={onLocale}
                options={(st.langOptions || []).map((o) => ({ value: o.code, label: o.label }))} />
            </div>
            {st.trayAvailable && (
              <div className="field">
                <span className="field-label">{t('tray_check')}</span>
                <Switch checked={!!st.settings.tray} onChange={onTray} />
              </div>
            )}
          </div>

          {(st.chests || []).map((c) => (
            <ChestCard key={c.place} chest={c} now={serverNow} t={t} onOpen={(p) => api.openChest(p)} />
          ))}
        </div>

        {/* 右欄 */}
        <div className="col right">
          <div className="panel history">
            <div className="history-head">
              <span className="history-title"><GiftOutlined /> {t('hist_title')}</span>
            </div>
            <Segmented block value={filter} onChange={setFilter}
              options={(st.filters || [{ key: 'all', label: '全部' }]).map((f) => ({ label: f.label, value: f.key }))} />
            <div className="grid">
              {history.length === 0
                ? <div className="grid-empty"><Empty description={t('hist_empty')} /></div>
                : history.map((it, i) => <HistoryCard key={`${it.assetId}-${it.ts}-${i}`} item={it} />)}
            </div>
          </div>
        </div>
        </div>
      </div>
    </ConfigProvider>
  )
}
