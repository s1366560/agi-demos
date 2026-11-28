import fs from 'node:fs/promises';
import path from 'node:path';

import { resolveConfig } from 'vite';

import packageJson from '../../package.json';

const PACKAGE_HOST_TITLE = 'MemStack · Project packages';
const WORKBENCH_TITLE = 'MemStack - AI Memory Cloud Platform';
const entryDocument = [
  `<head><title>${PACKAGE_HOST_TITLE}</title></head>`,
  '<script type="module" src="/src/projectPackages/main.tsx"></script>',
].join('');

async function entryTransformer(mode: string) {
  const config = await resolveConfig(
    { configFile: path.resolve(__dirname, '../../vite.config.ts'), mode },
    'serve'
  );
  const hook = config.plugins.find(
    (plugin) => plugin.name === 'full-client-entry'
  )?.transformIndexHtml;
  const handler = typeof hook === 'function' ? hook : hook?.handler;
  if (!handler) throw new Error(`The entry plugin is not registered in ${mode} mode`);
  return (html: string) => handler(html);
}

describe('entry document per build mode', () => {
  it('keeps the package host document outside the workbench modes', async () => {
    const transform = await entryTransformer('development');

    expect(await transform(entryDocument)).toBe(entryDocument);
  });

  it('gives the full workbench the signed host entry and title', async () => {
    const html = await (await entryTransformer('full'))(entryDocument);

    expect(html).toContain('src="/src/fullHost/main.tsx"');
    expect(html).not.toContain('/src/projectPackages/main.tsx');
    expect(html).toContain(`<title>${WORKBENCH_TITLE}</title>`);
  });

  it('keeps compat on the package host instead of the deleted business shell', async () => {
    const html = await (await entryTransformer('compat'))(entryDocument);

    expect(html).toContain('src="/src/projectPackages/main.tsx"');
    expect(html).not.toContain('/src/main.tsx');
  });

  it('keeps the original document head that the workbench modes open', async () => {
    const source = await fs.readFile(path.resolve(__dirname, '../../index.html'), 'utf8');

    expect(source).toContain(`<title>${PACKAGE_HOST_TITLE}</title>`);
    expect(source).toContain('src="/src/projectPackages/main.tsx"');
    // Typography, browser chrome tint and the loading fallback belong to the entry page.
    expect(source).toContain('fonts.googleapis.com/css2?family=Inter');
    expect(source).toContain('name="theme-color"');
    expect(source).toContain("classList.add('app-ready')");
  });
});

describe('Vite development server config', () => {
  it('allows shared workspace packages outside the web directory', async () => {
    const config = await resolveConfig(
      { configFile: path.resolve(__dirname, '../../vite.config.ts') },
      'serve'
    );

    expect(config.server.fs.allow).toContain(path.resolve(__dirname, '../../..'));
  });

  it('loads the TypeScript config explicitly in package scripts', () => {
    expect(packageJson.scripts.dev).toContain('--config vite.config.ts');
    expect(packageJson.scripts.build).toContain('--config vite.config.ts');
    expect(packageJson.scripts.preview).toContain('--config vite.config.ts');
  });
});
