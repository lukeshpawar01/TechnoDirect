/** @type {import('tailwindcss').Config} */
// Colours are CSS custom properties defined in src/index.css so light/dark
// swap in one place (see the dataviz palette notes in src/charts/palette.ts).
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        page: v('page'),
        surface: v('surface'),
        sunken: v('sunken'),
        line: v('line'),
        ink: v('ink'),
        ink2: v('ink2'),
        muted: v('muted'),
        brand: v('brand'),
        'brand-ink': v('brand-ink'),
        accent: v('accent'),
        good: v('good'),
        warn: v('warn'),
        bad: v('bad'),
        'good-bg': v('good-bg'),
        'warn-bg': v('warn-bg'),
        'bad-bg': v('bad-bg'),
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', '"Segoe UI"', 'Roboto', 'sans-serif'],
      },
      fontSize: { '2xs': ['0.6875rem', '1rem'] },
    },
  },
  plugins: [],
};
