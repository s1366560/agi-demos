// Keep signing and updater settings identical across the two host compositions.
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { parse } = require('yaml');
const desktop = resolve(__dirname, '..');

function buildConfiguration({ local, full }) {
  const config = parse(readFileSync(resolve(desktop, 'electron-builder.yml'), 'utf8'));
  if (!full) {
    config.extraResources = [
      {
        from: 'build/sidecar',
        to: 'sidecar',
        filter: ['agistack-desktop-sidecar*', 'SHA256SUMS'],
      },
    ];
    config.mac.binaries = ['Contents/Resources/sidecar/agistack-desktop-sidecar'];
    config.afterSign = 'scripts/signed-runtime-checksums.mjs';
    config.mac.sign = 'scripts/sign-package-host-macos.mjs';
  }
  if (local) {
    config.forceCodeSigning = false;
    config.publish = null;
    config.mac.identity = null;
    config.afterPack = full ? 'scripts/sign-local-cua-macos.mjs' : 'scripts/sign-local-macos.mjs';
  }
  return config;
}

module.exports = { buildConfiguration };
