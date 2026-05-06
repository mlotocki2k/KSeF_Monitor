/** @type {import('tailwindcss').Config} */
const path = require('path');

module.exports = {
  content: [
    path.join(__dirname, "templates/**/*.html"),
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
