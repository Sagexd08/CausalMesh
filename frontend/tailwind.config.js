/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Ground: warm off-black, never #000. Pure black crushes the
        // shadow detail every surface below depends on.
        ink: {
          950: "#0b0c0d",
          900: "#111315",
          850: "#16191c",
          800: "#1d2125",
          700: "#2a2f35",
          600: "#3a4149",
        },
        // Text ramp, neutral so the single accent stays the only hue.
        chalk: {
          100: "#f2f4f5",
          200: "#dfe3e6",
          400: "#a8b0b8",
          500: "#828b94",
          600: "#646d76",
        },
        // The one accent: desaturated signal-green. Under 80% saturation,
        // and deliberately not the purple/blue neon every AI product ships.
        signal: {
          DEFAULT: "#7dd3a0",
          dim: "#5aa87c",
          deep: "#2f6a4a",
        },
        // Arm identity. Sequential lightness on one hue family rather than
        // four competing colors: the arms are ordered, not categorical.
        arm: {
          c0: "#8b6f5c",
          c1: "#6b8fa8",
          c2: "#7dd3a0",
          c3: "#c2a878",
        },
      },
      fontFamily: {
        // Geist over Inter, which the taste skill bans for premium work.
        // System fallbacks first so the page renders correctly offline.
        sans: ["Geist", "Satoshi", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["Geist Mono", "JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      letterSpacing: { tightest: "-0.045em" },
      maxWidth: { prose: "65ch" },
      animation: { "fade-up": "fadeUp 0.6s cubic-bezier(0.16,1,0.3,1) both" },
      keyframes: {
        fadeUp: { "0%": { opacity: 0, transform: "translateY(12px)" }, "100%": { opacity: 1, transform: "none" } },
      },
    },
  },
  plugins: [],
};
