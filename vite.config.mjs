import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The React app lives in web/ and builds to web/dist, which the Express server serves
// as static assets. During `npm run dev:web`, Vite proxies the API to the Node server
// so the frontend can hot-reload against the real engine.
export default defineConfig({
  root: 'web',
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: `http://localhost:${process.env.PORT || 3000}`,
        changeOrigin: true,
      },
    },
  },
});
