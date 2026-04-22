/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#1d4ed8",
          light: "#3b82f6",
          dark: "#1e3a8a",
        },
      },
    },
  },
  plugins: [],
};
