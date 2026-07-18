/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'uni-blue': '#003087',
        'uni-red': '#E31837',
        'uni-dark': '#1a1a2e',
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
