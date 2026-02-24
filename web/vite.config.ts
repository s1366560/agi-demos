import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { visualizer } from "rollup-plugin-visualizer";
import { defineConfig } from "vite";


// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // Note: Ant Design 6+ has built-in tree-shaking support and uses CSS-in-JS
    // No additional plugin needed for on-demand imports
    // Bundle analyzer - generates stats.html after build
    visualizer({
      open: false,
      gzipSize: true,
      brotliSize: true,
      filename: "dist/stats.html",
    }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 3000,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
    },
    headers: {
      'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY',
      'Referrer-Policy': 'strict-origin-when-cross-origin',
      'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
    },
  },
  build: {
    outDir: "dist",
    rollupOptions: {
      output: {
        manualChunks: (id) => {
          // Vendor chunks for better caching
          if (id.includes("node_modules")) {
            // KaTeX & math plugins - separate async chunk for lazy loading
            if (id.includes("katex") || id.includes("remark-math") || id.includes("rehype-katex")) {
              return "vendor-math";
            }
            // Ant Design - large UI library
            if (id.includes("antd") || id.includes("@ant-design")) {
              return "vendor-antd";
            }
            // Icons
            if (id.includes("lucide-react") || id.includes("@ant-design/icons")) {
              return "vendor-icons";
            }
            // React ecosystem
            if (id.includes("react") || id.includes("react-dom") || id.includes("react-router")) {
              return "vendor-react";
            }
            // State management
            if (id.includes("zustand")) {
              return "vendor-state";
            }
            // Markdown and syntax highlighting
            if (id.includes("react-markdown") || id.includes("remark-gfm") || id.includes("react-syntax-highlighter")) {
              return "vendor-markdown";
            }
            // Terminal
            if (id.includes("@xterm") || id.includes("xterm")) {
              return "vendor-terminal";
            }
            // Charts
            if (id.includes("chart.js") || id.includes("react-chartjs")) {
              return "vendor-charts";
            }
            // Graph visualization
            if (id.includes("cytoscape")) {
              return "vendor-graph";
            }
            // i18n
            if (id.includes("i18next")) {
              return "vendor-i18n";
            }
            // PDF generation
            if (id.includes("html2pdf")) {
              return "vendor-pdf";
            }
            // Date utilities
            if (id.includes("date-fns")) {
              return "vendor-date";
            }
            // Other vendor
            return "vendor";
          }
        },
      },
    },
    // Report chunk sizes
    chunkSizeWarningLimit: 1000,
  },
});
