import { createRequire } from 'node:module';
import { cuaOptionsForFile, sealCuaMacApp } from './cua-packaging.mjs';

// Delegate the ordinary Electron signing flow, retaining its entitlements and
// configured identity. Only CUA component identifiers and their post-signing
// checksums are added before the app's final resource seal and notarization.
export default async function signCuaMacos(options) {
  const require = createRequire(import.meta.url);
  const electronRequire = createRequire(require.resolve('electron-builder'));
  const { sign } = electronRequire('app-builder-lib/out/codeSign/macCodeSign.js');
  const prior = options.optionsForFile;
  await sign({ ...options, optionsForFile: (path) => cuaOptionsForFile(path, options.app, prior?.(path) ?? {}) });
  await sealCuaMacApp(options.app, options.identity, { keychain: options.keychain });
}
