import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 相對路徑 base，讓 build 後的 dist 可從本機伺服器或 file:// 載入
export default defineConfig({
  base: './',
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true },
})
