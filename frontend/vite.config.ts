import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    // 与 tsconfig.json 的 paths 保持一致，否则 @/ 别名在 vite 侧解析不到
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      // 后端默认监听 8010（backend/run.py 的 DEFAULT_PORT），两边保持单一约定
      '/api': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
    },
  },
  // vite preview 用于验收构建产物，必须与 dev 保持同一套代理，
  // 否则预览环境下所有 /api 请求都会 404（构建产物验收的常见坑）
  preview: {
    host: '127.0.0.1',
    port: 4173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 2400,
  },
})
