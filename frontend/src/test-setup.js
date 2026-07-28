// Se ejecuta antes de cada archivo de test (ver `vitest.config.js`).
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  // Desmonta lo que quedara montado: sin esto, dos tests que rendericen el
  // mismo componente se encuentran dos copias en el DOM y las consultas por
  // texto fallan con "found multiple elements", que es un error que no habla
  // de lo que se estaba probando.
  cleanup()
  // `localStorage` es estado GLOBAL del entorno jsdom y sobrevive de un test
  // al siguiente. El acordeón guarda ahí la sección abierta, así que sin esta
  // línea el orden de los tests cambiaría su resultado.
  localStorage.clear()
})
