import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { LangProvider } from './i18n/index.jsx'
import './index.css'
import { applyScale } from './uiScale.js'

// Antes del primer pintado: si no, la página aparece un instante al 100 %
// y salta al tamaño guardado.
applyScale()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <LangProvider>
      <App />
    </LangProvider>
  </React.StrictMode>,
)
