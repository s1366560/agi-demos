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

function pageBuilds(pages, entries) {
  return Object.entries(entries).flatMap(([id, definition]) => {
    const candidates = pages.filter(page => page.id === id);
    if (typeof definition === 'string') {
      if (candidates.length !== 1) throw new Error('Expected one page declaration for ' + id);
      return [{ page: candidates[0], entry: definition }];
    }
    return Object.entries(definition).map(([target, entry]) => {
      const page = candidates.find(item => item.targets.length === 1 && item.targets[0] === target);
      if (!page) throw new Error('Missing target-specific page: ' + id + '/' + target);
      return { page, entry };
    });
  });
}

/** Compile package-owned entry points and update their signed contribution descriptors. */
export async function buildPackagePages({ root, sourceDirectory, entries, banner, contribution, plugins = [], resourceEntries = {} }) {
  const source = inside(root, sourceDirectory);
  const require = createRequire(join(source, 'package.json'));
  const { build } = require('esbuild');
  const descriptor = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'));
  const contractPath = inside(root, contribution ?? descriptor.contribution ?? 'contributions.json');
  const assetRoot = resolve(contractPath, '..');
  const contract = JSON.parse(await readFile(contractPath, 'utf8'));
  const outputs = new Map();
  for (const { page, entry } of pageBuilds(contract.pages, entries)) {
    const destination = inside(assetRoot, page.entry.path);
    const { outputFiles } = await build({
      entryPoints: [inside(source, entry)], outfile: destination,
      nodePaths: [join(source, 'node_modules')], plugins,
      tsconfigRaw: { compilerOptions: { jsx: 'react-jsx' } },
      bundle: true, platform: 'browser', format: 'iife', jsx: 'automatic', minify: true,
      define: { 'process.env.NODE_ENV': '"production"' }, legalComments: 'inline',
      ...(banner ? { banner } : {}), write: false,
    });
    for (const file of outputFiles) {
      const asset = file.path === destination ? page.entry : page.style;
      if (!asset || inside(assetRoot, asset.path) !== file.path) {
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
  const declared = new Set(contract.pages.flatMap((page) =>
    (page.resources ?? []).map((resource) => resource.path)));
  for (const [path, input] of Object.entries(resourceEntries)) {
    if (!declared.has(path)) throw new Error('Undeclared page resource: ' + path);
    const destination = inside(assetRoot, path);
    let contents = await readFile(inside(source, input));
    if (path.endsWith('.js')) {
      const { outputFiles } = await build({
        entryPoints: [inside(source, input)], outfile: destination, bundle: true,
        format: path.endsWith('.worker.js') ? 'iife' : 'esm', platform: 'browser',
        nodePaths: [join(source, 'node_modules')], jsx: 'automatic', minify: true,
        tsconfigRaw: { compilerOptions: { jsx: 'react-jsx' } },
        define: { 'process.env.NODE_ENV': '"production"' }, write: false,
      });
      if (outputFiles.length !== 1) throw new Error('Expected one resource: ' + path);
      contents = outputFiles[0].contents;
    }
    if (outputs.has(destination)) throw new Error('Conflicting resource: ' + path);
    const digest = 'sha256:' + createHash('sha256').update(contents).digest('hex');
    outputs.set(destination, { digest, contents });
  }
  // Shared entries, e.g. overview and detail, must resolve to the same bytes.
  for (const page of contract.pages) {
    for (const asset of [page.entry, page.style, ...(page.resources ?? [])].filter(Boolean)) {
      const path = inside(assetRoot, asset.path);
      const output = outputs.get(path);
      // Hand-authored scripts and styles are already at their final destination.
      asset.digest = output?.digest ?? 'sha256:' + createHash('sha256')
        .update(await readFile(path)).digest('hex');
    }
  }
  for (const [file, { contents }] of outputs) await writeFile(file, contents);
  await writeFile(contractPath, JSON.stringify(contract, null, 2) + '\n');
}
