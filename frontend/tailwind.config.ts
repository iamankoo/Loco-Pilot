import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./features/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ground: {
          DEFAULT: "#0a0a0b",
          raised: "#111113",
          overlay: "#17171a",
        },
        ivory: {
          DEFAULT: "#efe9dd",
          dim: "#b8b2a4",
          faint: "#7c766a",
        },
        gold: {
          DEFAULT: "#c6a15b",
          bright: "#dcb877",
          dim: "#8a7245",
          faint: "#4a3f2c",
        },
        line: {
          DEFAULT: "rgba(239, 233, 221, 0.09)",
          strong: "rgba(239, 233, 221, 0.16)",
        },
        status: {
          success: "#8fae7a",
          error: "#c0685c",
          running: "#c6a15b",
          pending: "#7c766a",
          cancelled: "#7c766a",
        },
      },
      fontFamily: {
        display: ["var(--font-display)", "Georgia", "serif"],
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      letterSpacing: {
        tightest: "-0.04em",
        widest2: "0.18em",
      },
      backgroundImage: {
        grain: "url('/grain.svg')",
      },
      keyframes: {
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.45" },
        },
        "fade-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "pulse-soft": "pulse-soft 2.2s ease-in-out infinite",
        "fade-up": "fade-up 0.4s ease-out",
      },
    },
  },
  plugins: [],
};

export default config;
