/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#2563eb",
          600: "#1d4ed8",
          700: "#1e40af",
        },
      },
      boxShadow: {
        panel: "0 16px 40px -24px rgba(15, 23, 42, 0.35)",
        premium: "0 24px 80px -48px rgba(15, 23, 42, 0.8)",
        glow: "0 0 0 1px rgba(96, 165, 250, 0.12), 0 22px 70px -48px rgba(37, 99, 235, 0.75)",
      },
    },
  },
  plugins: [],
};
