import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#0d1117",
          soft: "#161b22",
          line: "#232a33",
          950: "#0b1120",
          900: "#111827",
        },
        accent: {
          DEFAULT: "#4f7cff",
          hover: "#3d6bf0",
        },
        state: {
          ok: "#2ea043",
          warn: "#d29922",
          bad: "#f85149",
        },
        brand: {
          50: "#eef4ff",
          100: "#dbe7ff",
          200: "#b8cfff",
          300: "#8ab0ff",
          400: "#5c8bff",
          500: "#3d6bff",
          600: "#2952f0",
          700: "#2140c4",
          800: "#1e379c",
          900: "#1c327c",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "monospace"],
        display: ["var(--font-display)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;
