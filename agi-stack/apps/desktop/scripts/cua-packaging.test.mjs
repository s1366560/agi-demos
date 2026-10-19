import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { cuaOptionsForFile, refreshCuaChecksums, verifyCuaRuntime } from './cua-packaging.mjs';
import signLocalCuaMacos from './sign-local-cua-macos.mjs';
import { createCuaMacBundle, cuaMacBundleName, cuaMacExecutable } from './cua-layout.mjs';

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), '..');
test('CUA checksums reject altered files and symbolic links', async () => {
  const root = await mkdtemp(join(tmpdir(), 'memstack-cua-package-'));
  try {
    for (const name of ['cua-helper', 'memstack-cua-cloud-connectors']) {
      await writeFile(join(root, name), 'fixture-runtime', { mode: 0o755 });
    }
    await mkdir(join(root, 'cua-plugin/skills/computer-use'), { recursive: true });
    await writeFile(join(root, 'cua-plugin/skills/computer-use/SKILL.md'), 'fixture skill');
    await refreshCuaChecksums(root, 'fixture');
    await verifyCuaRuntime(root, { platform: 'fixture' });
    await writeFile(join(root, 'cua-helper'), 'altered-runtime');
    await assert.rejects(verifyCuaRuntime(root, { platform: 'fixture' }), /checksum mismatch/);
    await rm(join(root, 'cua-helper'));
    await symlink(join(root, 'memstack-cua-cloud-connectors'), join(root, 'cua-helper'));
    await assert.rejects(verifyCuaRuntime(root, { platform: 'fixture' }), /Invalid CUA runtime/);
  } finally { await rm(root, { recursive: true, force: true }); }
});
test('CUA signing adds exact identifiers and preserves Electron entitlements', () => {
  const prior = { entitlements: '/fixture/entitlements', hardenedRuntime: true, additionalArguments: ['--timestamp'] };
  const options = cuaOptionsForFile('/Fixture.app/Contents/Resources/sidecar/' + cuaMacExecutable, '/Fixture.app', prior);
  assert.equal(options.entitlements, prior.entitlements);
  assert.equal(options.hardenedRuntime, true);
  assert.deepEqual(options.additionalArguments, ['--timestamp', '--identifier', 'ai.agistack.desktop.cua-helper']);
  assert.equal(cuaOptionsForFile('/Unrelated.app/Contents/MacOS/main', '/Fixture.app', prior), prior);
});
test('macOS helper bundle has an accessory application identity and sealed resources', {
  skip: process.platform !== 'darwin',
}, async () => {
  const directory = await mkdtemp(join(tmpdir(), 'memstack-cua-bundle-'));
  try {
    const destination = join(directory, cuaMacBundleName);
    await createCuaMacBundle({ executable: join(desktop, 'cua-helper/bin/cua-helper'),
      lockedUse: join(desktop, 'cua-helper/bin/locked-use'), desktopRoot: desktop, destination });
    const plist = join(destination, 'Contents/Info.plist');
    const property = (key) => execFileSync('/usr/libexec/PlistBuddy', ['-c', 'Print :' + key, plist], { encoding: 'utf8' }).trim();
    assert.equal(property('CFBundleIdentifier'), 'ai.agistack.desktop.cua-helper');
    assert.equal(property('CFBundleDisplayName'), 'Memstack Computer Use');
    assert.equal(property('CFBundleExecutable'), 'cua-helper');
    assert.equal(property('LSUIElement'), 'true');
    assert.ok(property('NSMicrophoneUsageDescription'));
    assert.ok(property('NSAppleEventsUsageDescription'));
    await cp(join(desktop, '../../target/release/memstack-cua-cloud-connectors'), join(directory, 'memstack-cua-cloud-connectors'));
    await mkdir(join(directory, 'cua-plugin/skills/computer-use'), { recursive: true });
    await writeFile(join(directory, 'cua-plugin/skills/computer-use/SKILL.md'), 'fixture skill');
    await refreshCuaChecksums(directory, 'darwin');
    await verifyCuaRuntime(directory, { platform: 'darwin' });
    assert.match(await readFile(join(directory, 'CUA_SHA256SUMS'), 'utf8'), /Contents\/Info\.plist/);
    await writeFile(plist, (await readFile(plist, 'utf8')).replace('Memstack Computer Use', 'Changed helper identity'));
    await assert.rejects(verifyCuaRuntime(directory, { platform: 'darwin' }), /checksum mismatch/);
  } finally { await rm(directory, { recursive: true, force: true }); }
});
test('macOS local signing refreshes checksums and seals actual CUA resources', {
  skip: process.platform !== 'darwin',
}, async () => {
  const prepared = JSON.parse(execFileSync('python3', [join(desktop, 'cua-helper/tests/prepare_native_fixture.py')], { encoding: 'utf8' }));
  try {
    const appPath = prepared.bundle;
    await cp(join(desktop, 'build/sidecar'), join(appPath, 'Contents/Resources/sidecar'), { recursive: true });
    await createCuaMacBundle({ executable: join(desktop, 'cua-helper/bin/cua-helper'),
      lockedUse: join(desktop, 'cua-helper/bin/locked-use'), desktopRoot: desktop,
      destination: join(appPath, 'Contents/Resources/sidecar', cuaMacBundleName) });
    await signLocalCuaMacos({ electronPlatformName: 'darwin', appOutDir: dirname(appPath),
      packager: { appInfo: { productFilename: 'ComputerUseFixture' }, projectDir: desktop } });
    await verifyCuaRuntime(join(appPath, 'Contents/Resources/sidecar'), { platform: 'darwin' });
    execFileSync('/usr/bin/codesign', ['--verify', '--deep', '--strict', appPath]);
    assert.ok((await readFile(join(appPath, 'Contents/Resources/sidecar/CUA_SHA256SUMS'), 'utf8')).includes('cua-helper'));
  } finally { await rm(prepared.owned_temporary_root, { recursive: true, force: true }); }
});
