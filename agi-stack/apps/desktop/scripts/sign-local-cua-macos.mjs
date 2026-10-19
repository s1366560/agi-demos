import { join } from 'node:path';
import signLocalMacos from './sign-local-macos.mjs';
import { sealCuaMacApp } from './cua-packaging.mjs';

export default async function signLocalCuaMacos(context) {
  await signLocalMacos(context);
  if (context.electronPlatformName !== 'darwin') return;
  const appPath = join(context.appOutDir, context.packager.appInfo.productFilename + '.app');
  await sealCuaMacApp(appPath, '-', { timestamp: false });
}
