import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#0f172a",
          soft: "#1a1b1f",
          line: "#e8edf3",
          950: "#0f172a",
          900: "#1a1b1f",
        },
        accent: {
          DEFAULT: "#4c6fff",
          hover: "#3b5ce8",
        },
        robot: {
          DEFAULT: "#3bdcff",
          dark: "#1ec8ee",
        },
        state: {
          ok: "#22c55e",
          warn: "#d29922",
          bad: "#f85149",
        },
        brand: {
          50: "#eef7ff",
          100: "#d9eeff",
          200: "#b8e8ff",
          300: "#7ad8ff",
          400: "#3bdcff",
          500: "#4c6fff",
          600: "#3b5ce8",
          700: "#2f4bc4",
          800: "#1e379c",
          900: "#1c327c",
        },
        hero: {
          from: "#d7ecff",
          via: "#e8f3ff",
          to: "#f4ecff",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "Poppins", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-sans)", "Poppins", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "monospace"],
      },
      boxShadow: {
        card: "0 8px 30px -12px rgba(15, 23, 42, 0.12)",
        hero: "0 40px 80px -40px rgba(15, 23, 42, 0.28)",
      },
      borderRadius: {
        pill: "30px",
      },
    },
  },
  plugins: [],
} satisfies Config;
