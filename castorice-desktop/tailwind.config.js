/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        abyss: {
          950: "#05080f",
          900: "#0a0f1c",
          800: "#0f1729",
          700: "#172238",
          600: "#1e2d47",
        },
        biolum: {
          50: "#e6fbf7",
          100: "#b9f5e6",
          200: "#7ceed0",
          300: "#3ddfb8",
          400: "#12c7a0",
          500: "#05a682",
          600: "#02856a",
        },
        amber: {
          glow: "#ffb347",
          soft: "#ffd79a",
        },
        rose: {
          deep: "#ff6b9d",
        },
      },
      fontFamily: {
        display: ['"Cormorant Garamond"', "serif"],
        sans: ['"DM Sans"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      boxShadow: {
        glow: "0 0 20px rgba(5, 166, 130, 0.3)",
        "glow-lg": "0 0 40px rgba(5, 166, 130, 0.4)",
        "glow-amber": "0 0 20px rgba(255, 179, 71, 0.3)",
      },
      animation: {
        "pulse-slow": "pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "float": "float 6s ease-in-out infinite",
        "shimmer": "shimmer 2.5s linear infinite",
        "fade-in": "fadeIn 0.4s ease-out forwards",
        "slide-up": "slideUp 0.4s ease-out forwards",
      },
      keyframes: {
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-8px)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      backdropBlur: {
        xs: "2px",
      },
    },
  },
  plugins: [],
};
