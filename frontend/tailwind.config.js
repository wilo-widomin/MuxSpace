/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        panel: {
          bg: '#0d1117',
          surface: '#161b22',
          border: '#30363d',
          accent: '#2f81f7',
          muted: '#8b949e',
        },
      },
    },
  },
  plugins: [],
}
