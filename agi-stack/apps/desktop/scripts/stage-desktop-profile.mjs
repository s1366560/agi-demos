// Both profiles already built the Sidecar. Stage exactly the helpers their Main starts.
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const profile = process.env.AGISTACK_DESKTOP_PROFILE;
const full = profile === 'full' || profile === 'compat';
if (process.argv.includes('--build-sidecar')) {
  const args = ['build', '--manifest-path', 'sidecar/Cargo.toml', '--release'];
  if (profile === 'compat') args.push('--features', 'legacy-business');
  execFileSync('cargo', args, { stdio: 'inherit' });
} else {
  await stage();
}
async function stage() {
  if (full) {
    for (const [script, ...args] of [
      ['build-workspace-core.mjs', 'release'],
      ['stage-workspace-core.mjs'],
      ['build-cua-helper.mjs'],
      ['stage-cua-helper.mjs'],
      ['stage-cua-repl.mjs', '--universal'],
    ]) {
      execFileSync(process.execPath, [fileURLToPath(new URL(script, import.meta.url)), ...args], {
        stdio: 'inherit',
      });
    }
  }
  await import('./stage-sidecar.mjs');
}
