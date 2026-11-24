import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { isAbsolute, join, relative, resolve, sep } from 'node:path';

function inside(root, path) {
  const file = resolve(root, path);
  const name = relative(root, file);
  if (isAbsolute(path) || !name || name.startsWith('..' + sep) || name === '..' || isAbsolute(name)) {
    throw new Error('Expected a package-relative file: ' + path);
  }
  return file;
}

/** Compile package-owned entry points and update their signed contribution descriptors. */
export async function buildPackagePages({ root, sourceDirectory, entries, banner }) {
  const source = inside(root, sourceDirectory);
  const require = createRequire(join(source, 'package.json'));
  const { build } = require('esbuild');
  const descriptor = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
  const contractPath = inside(root, descriptor.contribution ?? 'contributions.json');
  const contract = JSON.parse(await readFile(contractPath, 'utf8'));
  const outputs = new Map();
  for (const [id, entry] of Object.entries(entries)) {
    const page = contract.pages.find((item) => item.id === id);
    if (!page) throw new Error('Unknown signed page: ' + id);
    const destination = inside(root, page.entry.path);
    const { outputFiles } = await build({
      entryPoints: [inside(source, entry)], outfile: destination,
      bundle: true, platform: 'browser', format: 'iife', jsx: 'automatic', minify: true,
      define: { 'process.env.NODE_ENV': '"production"' }, legalComments: 'inline',
      ...(banner ? { banner } : {}), write: false,
    });
    for (const file of outputFiles) {
      const asset = file.path === destination ? page.entry : page.style;
      if (!asset || inside(root, asset.path) !== file.path) {
        throw new Error('Page emits an undeclared asset: ' + file.path);
      }
      const digest = 'sha256:' + createHash('sha256').update(file.contents).digest('hex');
      if (outputs.has(file.path) && outputs.get(file.path).digest !== digest) {
        throw new Error('Conflicting page assets: ' + file.path);
      }
      asset.digest = digest;
      outputs.set(file.path, { digest, contents: file.contents });
    }
  }
  // Shared entries, e.g. overview and detail, must resolve to the same bytes.
  for (const page of contract.pages) {
    for (const asset of [page.entry, page.style].filter(Boolean)) {
      const output = outputs.get(inside(root, asset.path));
      if (output) asset.digest = output.digest;
    }
  }
  for (const [file, { contents }] of outputs) await writeFile(file, contents);
  await writeFile(contractPath, JSON.stringify(contract, null, 2) + '\n');
}
