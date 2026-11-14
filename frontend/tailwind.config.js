/**
 * HUASHU DESIGN SYSTEM — The Architects School
 * Grid systems · Pentagram restraint · strict typographic scales.
 *
 * Every colour below reads the same channel variables declared in
 * `src/index.css`. CSS owns the runtime channels (`--ink-900-c`), so the
 * `[data-theme="light"]` block can invert the whole ramp without touching a
 * single utility class. Keep the two files in sync.
 *
 * @type {import('tailwindcss').Config}
 */
const channel = (name) => `oklch(var(--${name}-c) / <alpha-value>)`;

const ink = {
  950: channel("ink-950"),
  900: channel("ink-900"),
  850: channel("ink-850"),
  800: channel("ink-800"),
  700: channel("ink-700"),
  600: channel("ink-600"),
  500: channel("ink-500"),
  400: channel("ink-400"),
  300: channel("ink-300"),
  200: channel("ink-200"),
  100: channel("ink-100"),
  50: channel("ink-50"),
};

const gold = {
  DEFAULT: channel("gold-400"),
  200: channel("gold-200"),
  300: channel("gold-300"),
  400: channel("gold-400"),
  500: channel("gold-500"),
  600: channel("gold-600"),
};

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink,
        gold,
        line: channel("line"),
        "line-strong": channel("line-strong"),
        fog: channel("fog"),
        paper: channel("paper"),
        text: {
          DEFAULT: channel("text"),
          muted: channel("text-muted"),
          faint: channel("text-faint"),
          inverse: channel("text-inverse"),
        },
        long: {
          DEFAULT: channel("long-400"),
          300: channel("long-300"),
          400: channel("long-400"),
          500: channel("long-500"),
          600: channel("long-500"),
        },
        short: {
          DEFAULT: channel("short-400"),
          300: channel("short-300"),
          400: channel("short-400"),
          500: channel("short-500"),
          600: channel("short-500"),
        },
        info: {
          DEFAULT: channel("info-400"),
          400: channel("info-400"),
          500: channel("info-500"),
        },
        warn: {
          DEFAULT: channel("warn-400"),
          400: channel("warn-400"),
          500: channel("warn-500"),
        },
      },
      fontFamily: {
        sans: ["Geist", "Inter", "Segoe UI", "system-ui", "-apple-system", "sans-serif"],
        mono: ["Geist Mono", "JetBrains Mono", "Cascadia Mono", "Consolas", "ui-monospace", "monospace"],
        display: ["Geist", "Space Grotesk", "Inter", "sans-serif"],
      },
      fontSize: {
        // Strict modular scale. Never invent an in-between size.
        display: ["clamp(2rem, 3.2vw + 0.5rem, 3.25rem)", { lineHeight: "1.04", letterSpacing: "-0.035em", fontWeight: "700" }],
        h1: ["clamp(1.5rem, 1.8vw + 0.5rem, 2.25rem)", { lineHeight: "1.1", letterSpacing: "-0.025em", fontWeight: "700" }],
        h2: ["clamp(1.25rem, 1.2vw + 0.5rem, 1.75rem)", { lineHeight: "1.16", letterSpacing: "-0.015em", fontWeight: "600" }],
        h3: ["1.125rem", { lineHeight: "1.25", letterSpacing: "-0.01em", fontWeight: "600" }],
        body: ["1rem", { lineHeight: "1.65" }],
        "body-lg": ["1.0625rem", { lineHeight: "1.65" }],
        "body-sm": ["0.875rem", { lineHeight: "1.6" }],
        "body-xs": ["0.8125rem", { lineHeight: "1.55" }],
        caption: ["0.75rem", { lineHeight: "1.5", letterSpacing: "0.04em", fontWeight: "500" }],
        "caption-sm": ["0.6875rem", { lineHeight: "1.45", letterSpacing: "0.07em", fontWeight: "500" }],
        micro: ["0.625rem", { lineHeight: "1.4", letterSpacing: "0.1em", fontWeight: "600" }],
        "tabular-lg": ["1.5rem", { lineHeight: "1.15", fontWeight: "600", fontFamily: "var(--font-mono)" }],
        "tabular-md": ["1.125rem", { lineHeight: "1.3", fontWeight: "600", fontFamily: "var(--font-mono)" }],
        "tabular-sm": ["0.875rem", { lineHeight: "1.4", fontWeight: "500", fontFamily: "var(--font-mono)" }],
      },
      borderRadius: {
        none: "0",
        xs: "1px",
        sm: "2px",
        DEFAULT: "2px",
        md: "4px",
        lg: "4px",
        xl: "6px",
        "2xl": "6px",
        "3xl": "8px",
        full: "9999px",
      },
      boxShadow: {
        card: "0 1px 0 oklch(1 0 0 / 0.03) inset, 0 2px 8px -2px oklch(0 0 0 / 0.6)",
        panel: "0 1px 0 oklch(1 0 0 / 0.02) inset, 0 8px 24px -14px oklch(0 0 0 / 0.8)",
        dropdown: "0 8px 32px -10px oklch(0 0 0 / 0.9), 0 2px 8px -4px oklch(0 0 0 / 0.5)",
        drawer: "-12px 0 40px -16px oklch(0 0 0 / 0.85)",
        focus: "0 0 0 2px oklch(0.64 0.15 72), 0 0 0 4px oklch(0.065 0.008 45)",
      },
      keyframes: {
        "slide-in": {
          "0%": { transform: "translateX(12px)", opacity: "0" },
          "100%": { transform: "translateX(0)", opacity: "1" },
        },
        "slide-in-y": {
          "0%": { transform: "translateY(8px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "fade-out": {
          "0%": { opacity: "1" },
          "100%": { opacity: "0" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.4" },
        },
        "pulse-ring": {
          "0%": { transform: "scale(1)", opacity: "0.5" },
          "100%": { transform: "scale(2)", opacity: "0" },
        },
      },
      animation: {
        "slide-in": "slide-in 180ms cubic-bezier(0.2, 0.9, 0.3, 1)",
        "slide-in-y": "slide-in-y 160ms cubic-bezier(0.2, 0.9, 0.3, 1)",
        "fade-in": "fade-in 140ms ease-out",
        "fade-out": "fade-out 140ms ease-in",
        "pulse-soft": "pulse-soft 2s ease-in-out infinite",
        "pulse-ring": "pulse-ring 1.6s ease-out infinite",
      },
      transitionTimingFunction: {
        architectural: "cubic-bezier(0.2, 0.9, 0.3, 1)",
      },
    },
  },
  plugins: [],
};
