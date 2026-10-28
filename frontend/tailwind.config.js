/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0b0c10",          // page background
        panel: "#101218",        // side panel
        bubble: "#1a1d26",       // assistant bubble
        accent: "#7aa2ff",       // restrained accent
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
      },
      keyframes: {
        dot: { "0%, 80%, 100%": { opacity: "0.25", transform: "translateY(0)" }, "40%": { opacity: "1", transform: "translateY(-2px)" } },
        fadeUp: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        breathe: { "0%, 100%": { transform: "scale(1)", opacity: "0.85" }, "50%": { transform: "scale(1.05)", opacity: "1" } },
      },
      animation: {
        dot: "dot 1.2s infinite ease-in-out",
        fadeUp: "fadeUp .28s ease-out both",
        breathe: "breathe 4.5s infinite ease-in-out",
      },
    },
  },
  plugins: [],
};
