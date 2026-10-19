import { randomUUID } from 'node:crypto';
import { cpSync, mkdirSync, renameSync, rmSync } from 'node:fs';
import { dirname } from 'node:path';

// macOS caches executable signature pages by vnode. Copying over a previously
// executed Mach-O can keep its inode and make a valid-on-disk signature fail at
// launch. Prepare a new bundle, then replace the old directory without writing
// to any of its executable inodes.
export function stageCuaMacBundle({ source, destination }) {
  const suffix = randomUUID();
  const staged = destination + '.stage-' + suffix;
  const previous = destination + '.previous-' + suffix;
  mkdirSync(dirname(destination), { recursive: true });
  try {
    cpSync(source, staged, { recursive: true, force: false, errorOnExist: true });
    let replaced = false;
    try {
      renameSync(destination, previous);
      replaced = true;
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    try {
      renameSync(staged, destination);
    } catch (error) {
      if (replaced) renameSync(previous, destination);
      throw error;
    }
    if (replaced) rmSync(previous, { recursive: true, force: true });
  } finally {
    rmSync(staged, { recursive: true, force: true });
  }
}
