import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    // `jsdom` y no `happy-dom`: el sidebar toca `localStorage`,
    // `window.innerHeight` y eventos de puntero, y jsdom es el que más se
    // parece a un navegador de verdad de los dos.
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.js'],
    // Los tests viven junto al código que prueban, no en un `__tests__`
    // aparte: así se ven al abrir la carpeta y es más difícil que uno se
    // quede huérfano tras un refactor.
    include: ['src/**/*.test.{js,jsx}'],
  },
})
