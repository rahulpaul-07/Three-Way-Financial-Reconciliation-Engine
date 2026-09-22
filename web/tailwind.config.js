/** @type {import('tailwindcss').Config} */
// Colours are CSS variables (see src/index.css) so the light "ledger paper"
// and dark "night ledger" themes share one set of utility names.
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        paper: v("paper"),
        sheet: v("sheet"),
        rule: v("rule"),
        ink: v("ink"),
        graphite: v("graphite"),
        tick: v("tick"),
        redink: v("redink"),
        pencil: v("pencil"),
        settled: v("settled"),
      },
      fontFamily: {
        serif: ['"Spectral"', "Georgia", "Cambria", "serif"],
        sans: ['"Public Sans"', "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: {
        // A modular scale (ratio 1.25) for the UI, plus two display steps.
        xs: ["0.75rem", { lineHeight: "1.1rem" }],
        sm: ["0.875rem", { lineHeight: "1.35rem" }],
        base: ["1rem", { lineHeight: "1.6rem" }],
        lg: ["1.25rem", { lineHeight: "1.8rem" }],
        xl: ["1.5625rem", { lineHeight: "2.1rem" }],
        "2xl": ["1.953rem", { lineHeight: "2.4rem" }],
        "3xl": ["2.441rem", { lineHeight: "2.8rem" }],
        display: ["clamp(2.4rem, 5.2vw, 4.2rem)", { lineHeight: "1.04", letterSpacing: "-0.018em" }],
      },
      maxWidth: { prose: "68ch", page: "76rem" },
      borderRadius: { sm: "3px", DEFAULT: "5px", lg: "9px" },
    },
  },
  plugins: [],
};
