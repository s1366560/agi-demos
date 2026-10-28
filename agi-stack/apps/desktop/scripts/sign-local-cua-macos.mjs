import { join } from 'node:path';
import signLocalMacos from './sign-local-macos.mjs';
import { sealCuaMacApp, signCuaNodeRuntime } from './cua-packaging.mjs';

export default async function signLocalCuaMacos(context) {
  if (context.electronPlatformName !== 'darwin') return;
  const identity = process.env.MEMSTACK_CUA_CODESIGN_IDENTITY?.trim() || '-';
  await signLocalMacos(context, { identity });
  const appPath = join(context.appOutDir, context.packager.appInfo.productFilename + '.app');
  await signCuaNodeRuntime(appPath, identity, { timestamp: false });
  await sealCuaMacApp(appPath, identity, { timestamp: false });
}
