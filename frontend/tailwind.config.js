/** Design tokens live in src/index.css as RGB channels so Tailwind opacity modifiers work (bg-accent/10). */
const token = (name) => `rgb(var(--c-${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: token('bg'),
        surface: token('surface'),
        surface2: token('surface2'),
        line: token('border'),
        fg: token('text'),
        muted: token('muted'),
        accent: token('accent'),
        profit: token('profit'),
        loss: token('loss'),
        warn: token('warn'),
        info: token('info'),
      },
      fontFamily: {
        sans: ['"Heebo Variable"', 'system-ui', 'Segoe UI', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgb(0 0 0 / 0.04), 0 1px 1px rgb(0 0 0 / 0.02)',
        pop: '0 12px 32px -8px rgb(0 0 0 / 0.35)',
      },
    },
  },
  plugins: [],
}
