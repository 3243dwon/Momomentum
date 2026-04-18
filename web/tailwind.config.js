/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: 'rgb(var(--ink-950) / <alpha-value>)',
          900: 'rgb(var(--ink-900) / <alpha-value>)',
          800: 'rgb(var(--ink-800) / <alpha-value>)',
          700: 'rgb(var(--ink-700) / <alpha-value>)',
          600: 'rgb(var(--ink-600) / <alpha-value>)',
          500: 'rgb(var(--ink-500) / <alpha-value>)'
        },
        zinc: {
          100: 'rgb(var(--text-100) / <alpha-value>)',
          200: 'rgb(var(--text-200) / <alpha-value>)',
          300: 'rgb(var(--text-300) / <alpha-value>)',
          400: 'rgb(var(--text-400) / <alpha-value>)',
          500: 'rgb(var(--text-500) / <alpha-value>)',
          600: 'rgb(var(--text-600) / <alpha-value>)'
        },
        signal: {
          up: 'rgb(var(--signal-up) / <alpha-value>)',
          down: 'rgb(var(--signal-down) / <alpha-value>)',
          warn: 'rgb(var(--signal-warn) / <alpha-value>)',
          info: 'rgb(var(--signal-info) / <alpha-value>)',
          flat: 'rgb(var(--signal-flat) / <alpha-value>)'
        }
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'SF Mono', 'Monaco', 'monospace']
      }
    }
  },
  plugins: []
};
