/** @type {import('tailwindcss').Config} */
// Colours are CSS variables (see src/index.css) so the light and dark
// themes share one set of utility names.
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
        violet: v("violet"),
      },
      fontFamily: {
        // One family throughout. `serif` is kept as a name because headings
        // and figures use it; it now means "display", set tighter.
        serif: ['"Geist Variable"', "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        sans: ['"Geist Variable"', "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ['"Geist Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
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
        display: ["clamp(2.5rem, 5.4vw, 4.4rem)", { lineHeight: "1.02", letterSpacing: "-0.04em" }],
      },
      maxWidth: { prose: "68ch", page: "76rem" },
      borderRadius: { sm: "6px", DEFAULT: "8px", md: "10px", lg: "14px" },
    },
  },
  plugins: [],
};
