import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  root: 'frontend',
  plugins: [vue()],
  base: '/',
  resolve: {
    alias: { '@': fileURLToPath(new URL('./frontend/src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:4173' },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
