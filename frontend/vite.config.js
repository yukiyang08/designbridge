import { fileURLToPath, URL } from 'node:url'

import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // 前端和後端共用根目錄的 .env：登入只需要 Supabase 網址與 anon 公開金鑰，
  // 逐一指定這兩個值，不能開放 SUPABASE_ 前綴（SUPABASE_SERVICE_ROLE_KEY 會一起被打包進瀏覽器）
  const env = loadEnv(mode, '..', '')
  return {
    plugins: [
      vue(),
      vueDevTools(),
    ],
    envDir: '..',
    define: {
      'import.meta.env.VITE_SUPABASE_URL': JSON.stringify(env.SUPABASE_URL),
      'import.meta.env.VITE_SUPABASE_ANON_KEY': JSON.stringify(env.SUPABASE_ANON_KEY),
    },
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url))
      },
    },
  }
})
