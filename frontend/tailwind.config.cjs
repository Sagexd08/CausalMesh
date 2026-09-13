/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Near-white ground with a dotted guide grid over it. The reference
        // is a technical product page: the page reads as graph paper, and
        // the data sits on it.
        paper: {
          DEFAULT: "#ffffff",
          raised: "#fbfbfa",
          sunk: "#f4f4f2",
        },
        ink: {
          900: "#101010",
          800: "#1c1c1c",
          700: "#3d3d3d",
          600: "#5f5f5f",
          500: "#8a8a8a",
          400: "#b4b4b4",
          300: "#d8d8d8",
          200: "#e8e8e6",
        },
        rule: {
          DEFAULT: "#101010",
          soft: "#e3e3e0",
          dot: "#d2d2ce",
        },
        // The highlighter. One saturated accent used as a marker swipe
        // behind a single word per headline, and nowhere else at full
        // strength — that restraint is what makes it land.
        marker: {
          DEFAULT: "#8ce619",
          deep: "#6fbe0f",
          wash: "#f0fbe0",
        },
        arm: {
          c0: "#c2410c",
          c1: "#6b7280",
          c2: "#6fbe0f",
          c3: "#a16207",
        },
      },
      fontFamily: {
        // Instrument Sans: engineered, slightly condensed, tight apertures.
        // Geist was here first and the design detector flagged it — it is on
        // every AI product page shipped this year, which is exactly the
        // convergence a distinctive face is supposed to avoid. Inter is
        // banned outright by the taste skill for the same reason.
        sans: [
          "Outfit",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
        display: [
          "Cabinet Grotesk",
          "Outfit",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      letterSpacing: { tightest: "-0.035em" },
      // Cabinet Grotesk for display only: heavier, more condensed, with the
      // engineered feel the reference has at large sizes. Satoshi carries
      // body copy, where Cabinet is too characterful to read at length.
      maxWidth: { prose: "62ch" },
    },
  },
  plugins: [],
};
