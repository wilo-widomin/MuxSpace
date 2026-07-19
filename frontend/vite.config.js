import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// El proxy redirige las llamadas /api al backend FastAPI durante el
// desarrollo, evitando problemas de CORS y centralizando el origen.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // Necesario para el WebSocket del terminal (/api/terminal/{name});
        // al pasar por el proxy, la cookie de sesión viaja con el handshake.
        ws: true,
      },
    },
  },
})
