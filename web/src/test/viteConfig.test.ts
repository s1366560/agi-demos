import path from 'node:path';

import { resolveConfig } from 'vite';

import packageJson from '../../package.json';

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
