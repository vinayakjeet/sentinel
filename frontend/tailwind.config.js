/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"] },
      colors: {
        ink: {
          950: "#070c17",
          900: "#0c1322",
          850: "#111a2e",
          800: "#16213a",
          700: "#213052",
          600: "#2f4068",
          500: "#4a5c85",
          400: "#6b7ca3",
          300: "#93a2c4",
          200: "#b9c4de",
          100: "#dbe2f1",
          50: "#eef2fa",
        },
        steel: { DEFAULT: "#7fb0ff", dim: "#4d7fcf" },
        // Band colours are the only saturated colours in the app: colour always means risk.
        band: {
          approve: "#34c9a6",
          stepup: "#e8c14a",
          review: "#f08a3c",
          decline: "#f0565f",
        },
      },
      fontSize: { "2xs": ["0.6875rem", { lineHeight: "1rem" }] },
    },
  },
  plugins: [],
};
