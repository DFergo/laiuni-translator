/** @type {import('tailwindcss').Config} */
// Colors are CSS variables (defaults in index.css) so a deployed frontend can
// override branding at runtime without a rebuild (DESIGN.md — branding is
// per-frontend, read at runtime).
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: 'var(--color-primary)',
        secondary: 'var(--color-secondary)',
        accent: 'var(--color-accent)',
        bg: 'var(--color-bg)',
        surface: 'var(--color-surface)',
        'text-primary': 'var(--color-text-primary)',
        'text-secondary': 'var(--color-text-secondary)',
        border: 'var(--color-border)',
        danger: 'var(--color-danger)',
      },
      borderRadius: {
        sm: '8px',
        md: '12px',
        lg: '20px',
      },
      maxWidth: {
        flow: '640px',
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
