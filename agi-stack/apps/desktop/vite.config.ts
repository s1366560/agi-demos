import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { rendererRootHotReload } from "./scripts/rendererRootHotReload.mjs";

export default defineConfig({
  base: "./",
  plugins: [rendererRootHotReload(__dirname), react()],
  resolve: {
    dedupe: ["react", "react-dom", "@radix-ui/themes", "@radix-ui/react-icons"],
    alias: {
      "@desktop": path.resolve(__dirname, "src"),
      "@business": path.resolve(__dirname, "../../../plugins/business"),
      "@agistack/plugin-runtime": path.resolve(
        __dirname,
        "../../packages/plugin-runtime/src/index.ts",
      ),
      "@agistack/plugin-slots": path.resolve(
        __dirname,
        "../../packages/plugin-slots/src/index.ts",
      ),
    },
  },
  server: { fs: { allow: [path.resolve(__dirname, "../../..")] } },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
