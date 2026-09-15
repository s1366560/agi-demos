import { resolve } from 'node:path';

/**
 * The generation store is owned by main.tsx's React root. Fast Refresh may
 * replace a dependency of that store while retaining the root, so these
 * updates must restart the document instead of replacing part of its graph.
 *
 * @param {string} desktopRoot
 * @returns {import('vite').Plugin}
 */
export function rendererRootHotReload(desktopRoot) {
  const rootModule = resolve(
    desktopRoot,
    'src/plugins/useDesktopPluginGenerationV2.ts',
  ).replaceAll('\\', '/');

  return {
    name: 'desktop-renderer-root-hot-reload',
    apply: 'serve',
    enforce: 'pre',
    handleHotUpdate(context) {
      const pending = context.modules.filter((module) => module.type !== 'css');
      const visited = new Set();
      while (pending.length > 0) {
        const module = pending.pop();
        if (!module || visited.has(module)) continue;
        visited.add(module);
        if (module.file?.replaceAll('\\', '/') === rootModule) {
          context.server.ws.send({ type: 'full-reload', path: '*' });
          return [];
        }
        pending.push(...module.importers);
      }
    },
  };
}
