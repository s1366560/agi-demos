import { defineConfig } from 'vite';
import { vitePluginSinglefile } from 'vite-plugin-singlefile';

export default defineConfig({
  plugins: [vitePluginSinglefile()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: 'mcp-app.html',
      output: {
        entryFileNames: 'mcp-app.html',
        assetFileNames: '[name].[ext]'
      }
    }
  }
});
