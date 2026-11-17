import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/metrics': 'http://127.0.0.1:8000',
      '/processes': 'http://127.0.0.1:8000',
      '/services': 'http://127.0.0.1:8000',
      '/incidents': 'http://127.0.0.1:8000',
      '/system': 'http://127.0.0.1:8000',
      '/guardrails': 'http://127.0.0.1:8000',
      '/recovery': 'http://127.0.0.1:8000',
      '/faults': 'http://127.0.0.1:8000',
      '/api': 'http://127.0.0.1:8000',
    },
  },
});
