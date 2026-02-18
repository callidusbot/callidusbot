import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0f1117",
        surface: "#1a1d27",
        surfaceHover: "#22263a",
        border: "#2a2d3e",
        primary: "#5865F2",
        primaryHover: "#4752c4",
        danger: "#ed4245",
        dangerHover: "#c03537",
        success: "#57F287",
        warning: "#FEE75C",
        textPrimary: "#e3e5e8",
        textSecondary: "#a3a6b1",
        textMuted: "#6d7080",
      },
    },
  },
  plugins: [],
};
export default config;
