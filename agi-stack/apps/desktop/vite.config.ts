import { richPageFramePlugin } from '../../packages/plugin-slots/viteRichPageFrame.mjs';
import { compatibilityProfile, fullDesktopProfile, legacyRendererEntry } from './scripts/legacyRendererProfile';
import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { rendererRootHotReload } from "./scripts/rendererRootHotReload.mjs";

export default defineConfig({
  base: "./",
  plugins: [rendererRootHotReload(__dirname), react(), richPageFramePlugin(), ...(fullDesktopProfile ? [legacyRendererEntry] : [])],
  resolve: {
    dedupe: ['@xterm/addon-fit', '@xterm/addon-web-links', '@xterm/xterm', "react", "react-dom", "@radix-ui/themes", "@radix-ui/react-icons"],
    alias: {
      "@desktop": path.resolve(__dirname, "src"),
      ...(fullDesktopProfile ? {"@business": path.resolve(__dirname, "../../../plugins/business")} : {}),
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
