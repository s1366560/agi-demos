// tsc preserves Vite's raw imports. Serve the guest bootstrap to Node tests as the same string.
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';

const guest = new URL('../../../packages/plugin-slots/src/richPageGuest.js', import.meta.url);
const moduleUrl = new URL('./richPageGuest.raw.cjs', import.meta.url).href;

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === './richPageGuest.js?raw' && context.parentURL?.endsWith('/plugin-slots/src/richPage.js')) {
      return { url: moduleUrl, format: 'commonjs', shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url === moduleUrl) {
      const source = 'module.exports = ' + JSON.stringify(readFileSync(guest, 'utf8'));
      return { format: 'commonjs', source, shortCircuit: true };
    }
    return nextLoad(url, context);
  },
});
