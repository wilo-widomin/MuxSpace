// Configuración plana de eslint (US-008).
//
// Deliberadamente corta. El frontend son ~20 archivos y un preajuste pesado
// (airbnb y compañía) traería cientos de reglas de estilo que este repo no
// sigue, y el arreglo sería reescribirlo entero — justo lo que esta historia
// deja fuera de alcance.
//
// Lo que sí tiene que estar son las dos reglas de hooks: son las únicas que
// detectan bugs de verdad (un hook dentro de un `if`, un efecto al que le
// falta una dependencia y se queda con un valor viejo). El resto es ruido
// comparado con eso.
import js from '@eslint/js'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'

export default [
  {
    // `dist` es la salida de vite y `node_modules` un symlink al repo
    // principal (ver contexto-tecnico.md): lintar cualquiera de los dos es
    // revisar código que no escribimos.
    ignores: ['dist/**', 'node_modules/**'],
  },
  js.configs.recommended,
  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.es2021 },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { react, 'react-hooks': reactHooks },
    // Versión fija y no `detect`: el autodetector de eslint-plugin-react 7.37
    // llama a `context.getFilename()`, que eslint 10 ya no expone, y revienta
    // el linter entero antes de mirar una sola línea de código.
    settings: { react: { version: '18.3' } },
    rules: {
      ...react.configs.flat.recommended.rules,
      // React 17+ con el nuevo transform de JSX: no hace falta importar React
      // para usar JSX, y `prop-types` es un sistema de tipos que este proyecto
      // no usa (ni empezará a usar en un PR de linters).
      'react/react-in-jsx-scope': 'off',
      'react/prop-types': 'off',
      // Las dos que justifican tener eslint.
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // Una variable sin usar es casi siempre un resto de un refactor a medias.
      // Se permite el prefijo `_` para lo que se ignora a propósito, y las
      // mayúsculas para los `catch (E)` de librerías.
      'no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^[_A-Z]' },
      ],
    },
  },
]

// `scripts/check-i18n.js` (fuera de `frontend/`) NO se linta: eslint 10 solo
// resuelve la configuración para archivos bajo el directorio que la contiene,
// y sacarla a la raíz del repo para cubrir un archivo es un cambio de
// estructura que no toca a esta historia.
