/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#080B10",
          900: "#0C1118",
          850: "#101720",
          800: "#141D28",
          700: "#1B2836",
          600: "#243445",
        },
        line: "#22303F",
        fog: "#8B9BB0",
        paper: "#E7EEF7",
        gold: {
          300: "#F0D089",
          400: "#E7BC60",
          500: "#D9A63C",
          600: "#B9852A",
        },
        long: "#3FB950",
        short: "#F0616D",
        info: "#5BA8F5",
        warn: "#E3A008",
      },
      fontFamily: {
        sans: [
          "Inter",
          "Segoe UI",
          "system-ui",
          "-apple-system",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "Cascadia Mono",
          "Consolas",
          "ui-monospace",
          "monospace",
        ],
      },
      boxShadow: {
        panel: "0 1px 0 rgba(255,255,255,0.04) inset, 0 18px 40px -24px rgba(0,0,0,0.9)",
        drawer: "-24px 0 60px -20px rgba(0,0,0,0.8)",
      },
      keyframes: {
        "slide-in": {
          "0%": { transform: "translateX(24px)", opacity: "0" },
          "100%": { transform: "translateX(0)", opacity: "1" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        pulseSoft: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
      },
      animation: {
        "slide-in": "slide-in 180ms ease-out",
        "fade-in": "fade-in 140ms ease-out",
        pulseSoft: "pulseSoft 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
