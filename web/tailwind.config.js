/** @type {import('tailwindcss').Config} */
// Colours are CSS variables (see src/index.css) so the light "counting-house
// ledger" and dark "gaslight" themes share one set of utility names.
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
        brass: v("brass"),
      },
      fontFamily: {
        // Display: a high-contrast Didone, the face of Victorian letterpress.
        serif: ['"Playfair Display"', "Georgia", "Cambria", "serif"],
        // Reading text and controls: a book serif. `sans` is kept as the
        // name so the utilities already in use pick it up unchanged.
        sans: ['"Spectral"', "Georgia", "Cambria", "serif"],
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
      // Square, as ruled paper and letterpress are. Status dots stay round.
      borderRadius: { sm: "0px", DEFAULT: "1px", md: "1px", lg: "2px" },
    },
  },
  plugins: [],
};
