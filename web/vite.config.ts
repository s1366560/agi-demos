import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { visualizer } from "rollup-plugin-visualizer";
import { defineConfig } from "vite";

const getPackageName = (id: string): string | null => {
  const normalized = id.split("\\").join("/");
  const marker = "/node_modules/";
  const markerIndex = normalized.lastIndexOf(marker);

  if (markerIndex === -1) {
    return null;
  }

  const packagePath = normalized.slice(markerIndex + marker.length);
  const [scopeOrName, scopedName] = packagePath.split("/");

  if (!scopeOrName) {
    return null;
  }

  return scopeOrName.startsWith("@") && scopedName ? `${scopeOrName}/${scopedName}` : scopeOrName;
};

const packageIs = (packageName: string, packages: readonly string[]): boolean =>
  packages.includes(packageName);


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
      'Permissions-Policy': 'camera=(self), microphone=(self), geolocation=()',
    },
  },
  build: {
    outDir: "dist",
    rollupOptions: {
      output: {
        manualChunks: (id) => {
          // Vendor chunks for better caching
          if (id.includes("node_modules")) {
            const packageName = getPackageName(id);

            if (!packageName) {
              return "vendor";
            }

            // KaTeX & math plugins - separate async chunk for lazy loading
            if (packageIs(packageName, ["katex", "remark-math", "rehype-katex"])) {
              return "vendor-math";
            }
            // Ant Design - large UI library
            if (
              packageName === "antd" ||
              packageIs(packageName, ["@ant-design/colors", "@ant-design/cssinjs"])
            ) {
              return "vendor-antd";
            }
            if (packageName.startsWith("@rc-component/") || packageName.startsWith("@ant-design/")) {
              return "vendor-antd-addons";
            }
            // Icons
            if (packageName === "lucide-react") {
              return "vendor-icons";
            }
            // React ecosystem
            if (
              packageIs(packageName, [
                "react",
                "react-dom",
                "react-is",
                "react-router",
                "react-router-dom",
                "scheduler",
              ])
            ) {
              return "vendor-react";
            }
            // State management
            if (packageIs(packageName, ["zustand", "@tanstack/react-query", "swr"])) {
              return "vendor-state";
            }
            if (packageName === "@tanstack/query-core") {
              return "vendor-state-core";
            }
            // Markdown and syntax highlighting
            if (
              packageIs(packageName, [
                "react-markdown",
                "remark-gfm",
                "rehype-raw",
                "unified",
                "remark-parse",
                "remark-rehype",
                "markdown-it",
                "parse5",
                "dompurify",
                "js-yaml",
              ])
            ) {
              return "vendor-markdown";
            }
            if (
              packageIs(packageName, [
                "react-syntax-highlighter",
                "highlight.js",
                "refractor",
                "lowlight",
                "prismjs",
              ])
            ) {
              return "vendor-code";
            }
            // Terminal
            if (packageName.startsWith("@xterm/")) {
              return "vendor-terminal";
            }
            // Charts
            if (packageIs(packageName, ["chart.js", "react-chartjs-2"])) {
              return "vendor-charts";
            }
            // 3D visualization (R3F)
            if (
              packageName.startsWith("@react-three/") ||
              packageIs(packageName, [
                "three-stdlib",
                "three-mesh-bvh",
                "troika-three-text",
                "troika-three-utils",
                "meshline",
                "maath",
                "camera-controls",
              ])
            ) {
              return "vendor-3d";
            }
            if (packageName === "three") {
              return "vendor-three";
            }
            // Graph visualization
            if (
              packageIs(packageName, [
                "cytoscape",
                "cytoscape-fcose",
                "cytoscape-cose-bilkent",
                "cose-base",
              ])
            ) {
              return "vendor-graph";
            }
            // i18n
            if (packageIs(packageName, ["i18next", "i18next-browser-languagedetector"])) {
              return "vendor-i18n";
            }
            // PDF generation
            if (packageName === "html2pdf.js") {
              return "vendor-pdf";
            }
            if (packageIs(packageName, ["html2canvas", "jspdf", "jszip"])) {
              return "vendor-document-render";
            }
            if (packageName === "docx-preview") {
              return "vendor-docx";
            }
            if (packageName === "xlsx") {
              return "vendor-spreadsheet";
            }
            if (
              packageIs(packageName, [
                "@mcp-ui/client",
                "@modelcontextprotocol/sdk",
                "@a2ui/lit",
                "@a2ui/web_core",
                "@copilotkit/a2ui-renderer",
                "@copilotkit/react-core",
                "vscode-languageserver-types",
              ])
            ) {
              return "vendor-agent-ui";
            }
            if (packageName === "mermaid") {
              if (!id.includes("/chunks/mermaid.core/")) {
                return "vendor-mermaid-core";
              }

              return id.includes("/chunks/mermaid.core/chunk-")
                ? "vendor-mermaid-shared"
                : "vendor-mermaid-diagrams";
            }
            if (
              packageIs(packageName, [
                "@mermaid-js/parser",
                "langium",
                "chevrotain",
                "layout-base",
                "dagre-d3-es",
                "elkjs",
                "khroma",
              ])
            ) {
              return "vendor-diagrams";
            }
            if (packageIs(packageName, ["zod", "zod-to-json-schema", "ajv", "ajv-formats"])) {
              return "vendor-schema";
            }
            if (packageIs(packageName, ["axios", "cookie", "set-cookie-parser"])) {
              return "vendor-network";
            }
            // Date utilities
            if (packageIs(packageName, ["date-fns", "dayjs"])) {
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
